# coding: utf-8
import sublime

import webbrowser
import html
from functools import partial as bind

from util import catch, Pretty
from notes import Note
from outgoing import AddImportRefactorDesc, TypeCheckFilesReq
from patch import fromfile
from config import feedback, gconfig
from symbol_format import completion_to_suggest, type_to_show
from paths import root_as_str_from_abspath, relative_path


class ProtocolHandler(object):
    """Mixin for common behavior of handling ENSIME protocol responses.

    Actual handler implementations are abstract and should be implemented by a
    subclass. Requires facilities of an ``EnsimeClient``.
    """

    def __init__(self):
        self.server_version = "unknown"
        self.handlers = {}
        self.register_responses_handlers()

    def register_responses_handlers(self):
        """Register handlers for responses from the server.

        A handler must accept only one parameter: `payload`.
        """
        self.handlers["ConnectionInfo"] = self.handle_connection_info
        self.handlers["SendBackgroundMessageEvent"] = self.handle_background_message
        self.handlers["SymbolInfo"] = self.handle_symbol_info
        self.handlers["IndexerReadyEvent"] = self.handle_indexer_ready
        self.handlers["AnalyzerReadyEvent"] = self.handle_analyzer_ready
        self.handlers["NewScalaNotesEvent"] = self.handle_scala_notes
        self.handlers["NewJavaNotesEvent"] = self.handle_java_notes
        self.handlers["ClearAllScalaNotesEvent"] = self.handle_clear_scala_notes
        self.handlers["BasicTypeInfo"] = self.show_type
        self.handlers["ArrowTypeInfo"] = self.show_type
        self.handlers["FullTypeCheckCompleteEvent"] = self.handle_typecheck_complete
        self.handlers["StringResponse"] = self.handle_string_response
        self.handlers["CompletionInfoList"] = self.handle_completion_info_list
        self.handlers["SymbolSearchResults"] = self.handle_symbol_search
        self.handlers["DebugOutputEvent"] = self.handle_debug_output
        self.handlers["DebugBreakEvent"] = self.handle_debug_break
        self.handlers["DebugBacktrace"] = self.handle_debug_backtrace
        # self.handlers["DebugVmError"] = self.handle_debug_vm_error
        self.handlers["RefactorDiffEffect"] = self.apply_refactor
        self.handlers["ImportSuggestions"] = self.handle_import_suggestions
        # self.handlers["PackageInfo"] = self.handle_package_info

    def handle_incoming_response(self, call_id, payload):
        """Get a registered handler for a given response and execute it."""
        self.env.logger.debug('handle_incoming_response: in [typehint: %s, call ID: %s]',
                              payload['typehint'], call_id)  # We already log the full JSON response

        typehint = payload["typehint"]
        handler = self.handlers.get(typehint)

        def feature_not_supported(m):
            msg = feedback["handler_not_implemented"]
            self.env.logger.error(msg.format(typehint, self.server_version))
            self.env.status_message(msg.format(typehint, self.server_version))

        if handler:
            with catch(NotImplementedError, feature_not_supported):
                handler(call_id, payload)
        else:
            self.env.logger.warning('Response has not been handled: %s', Pretty(payload))

    def handle_connection_info(self, call_id, payload):
        self.server_version = payload.get("version", "unknown")
        self.env.logger.info("Connected to the ensime server {} through websocket. \
Please wait while we get the analyzer and indexer ready. Indexing files may take a while and \
consequently the context menu commands may take longer to get enabled. You may check the server\
.log to see what's currently indexing or if any error occured while indexing."
                             .format(self.server_version))

    def handle_background_message(self, call_id, payload):
        self.env.logger.info("{} : {}"
                             .format(payload.get("code", "unknown code"),
                                     payload.get("detail", "no detail")))

    def handle_indexer_ready(self, call_id, payload):
        self.indexer_ready = True  # used to enable commands that depend on indexer
        self.env.logger.info("Indexer is ready. Context menu commands are alive! :D")

    def handle_analyzer_ready(self, call_id, payload):
        self.analyzer_ready = True  # used to enable commands that depend on analyzer
        self.env.logger.info("Analyzer is ready.")
        files = []
        for view in self.env.window.views():
            files.append(view.file_name())
        TypeCheckFilesReq(files).run_in(self.env, async=True)

    def handle_scala_notes(self, call_id, payload):
        self.env.notes_storage.append(map(Note, payload['notes']))

    def handle_java_notes(self, call_id, payload):
        pass

    def handle_clear_scala_notes(self, call_id, payload):
        self.env.notes_storage.clear()

    def handle_typecheck_complete(self, call_id, payload):
        self.env.editor.redraw_all_highlights()
        self.env.logger.info("Handled FullTypecheckCompleteEvent. Redrawing highlights.")

    def handle_debug_vm_error(self, call_id, payload):
        raise NotImplementedError()

    def handle_import_suggestions(self, call_id, payload):
        imports = list()
        for suggestions in payload['symLists']:
            for suggestion in suggestions:
                imports.append(suggestion['name'].replace('$', '.'))
        imports = list(sorted(set(imports)))

        if not imports:
            self.env.error_message('No import suggestions found.')
            return

        def do_refactor(choice):
            if choice > -1:
                file_name = self.call_options[call_id].get('file_name')
                # request is async, file is reverted when patch is received and applied
                AddImportRefactorDesc(file_name, imports[choice]).run_in(self.env, async=True)

        sublime.set_timeout(bind(self.env.window.show_quick_panel, imports, do_refactor), 0)

    def handle_package_info(self, call_id, payload):
        raise NotImplementedError()

    def handle_symbol_search(self, call_id, payload):
        """Handler for symbol search results"""
        self.env.logger.debug("handle_symbol_search: in {}".format(Pretty(payload)))
        item_list = []
        location_list = []
        syms = payload["syms"]
        for sym in syms:
            p = sym.get("pos")
            if p:
                location_list.append((p["file"], p["line"] + 1))
                path = relative_path(self.env.project_root, str(p["file"]))
                path_to_display = path if path is not None else str(p["file"])
                item_list.append(["{}".format(str(sym["name"]).replace("$", ".")),
                                  "[Line {}] {}".format(p["line"] + 1,
                                                        path_to_display)])

        def open_item(index):
            if index == -1:
                return
            loc = location_list[index]
            self.env.window.open_file("{}:{}:{}".format(loc[0], loc[1], 1),
                                      sublime.ENCODED_POSITION)

        sublime.set_timeout(bind(self.env.window.show_quick_panel, item_list, open_item), 0)

    def handle_symbol_info(self, call_id, payload):
        decl_pos = payload.get("declPos")
        if decl_pos is None:
            self.env.error_message("Couldn't find the declaration position for symbol.\n{}"
                                   .format(payload.get("name")))
            return
        f = decl_pos.get("file")
        if f is None:
            self.env.error_message("Couldn't find the file where it's defined.")
            return
        self.env.logger.debug("Jumping to file : {}".format(f))
        view = self.env.window.open_file(f)

        # either has line or offset
        def _scroll_once_loaded(attempts=10):
            offset = decl_pos.get("offset")
            line = decl_pos.get("line")
            if not offset and not line:
                self.env.logger.debug("No offset or line number were found.")
                return
            while view.is_loading() and attempts:
                sublime.set_timeout(_scroll_once_loaded, 100)
                attempts -= 1
            if not view.is_loading():
                if not offset:
                    offset = view.text_point(line + 1, 1)
                self.env.logger.debug("Scrolling to offset : {}".format(offset))
                view.sel().clear()
                view.sel().add(sublime.Region(offset))
                view.show_at_center(offset)
            else:
                self.env.logger.debug("Scrolling failed as the view wasn't ready.")

        sublime.set_timeout(_scroll_once_loaded, 0)

    def handle_string_response(self, call_id, payload):
        """Handler for response `StringResponse`.

        This is the response for the following requests:
          1. `DocUriAtPointReq` or `DocUriForSymbolReq`
          2. `DebugToStringReq`
        """

        # :EnDocBrowse or :EnDocUri
        url = payload['text']
        if not url.startswith('http'):
            port = self.ensime.http_port()
            url = gconfig['localhost'].format(port, url)

        options = self.call_options.get(call_id)
        if options and options.get('browse'):
            sublime.set_timeout(bind(self._browse_doc, self.env, url), 0)
            del self.call_options[call_id]
        else:
            pass
            # TODO: make this return value of a Vim function synchronously, how?
            # self.env.logger.debug('EnDocUri %s', url)
            # return url

    def _browse_doc(self, env, url):
        try:
            if webbrowser.open(url):
                env.logger.info('opened %s', url)
        except webbrowser.Error:
            env.logger.exception('_browse_doc: webbrowser error')
            env.error_message(feedback["manual_doc"].format(url))

    def handle_completion_info_list(self, call_id, payload):
        """Handler for a completion response."""
        prefix = payload.get("prefix")
        if (self.env.editor.current_prefix is not None and
                self.env.editor.current_prefix == prefix):
            self.env.logger.debug('handle_completion_info_list: in async')

            def _hack(prefix):
                if (sublime.active_window().active_view().is_auto_complete_visible() and
                        self.env.editor.current_prefix == prefix):
                    sublime.active_window().run_command("hide_auto_complete")
                    completions = [c for c in payload["completions"] if "typeInfo" in c]
                    self.env.editor.suggestions = [completion_to_suggest(c) for c in completions]

                    def hack2():
                        sublime.active_window().active_view().run_command("auto_complete")
                    sublime.set_timeout(hack2, 1)
            sublime.set_timeout(bind(_hack, prefix), 0)

        else:
            self.env.editor.current_prefix = payload.get("prefix")
            self.env.logger.debug('handle_completion_info_list: in sync')
            # filter out completions without `typeInfo` field to avoid server bug. See #324
            completions = [c for c in payload["completions"] if "typeInfo" in c]
            self.env.editor.suggestions = [completion_to_suggest(c) for c in completions]
            self.env.logger.debug('handle_completion_info_list: {}'
                                  .format(Pretty(self.env.editor.suggestions)))

    def apply_refactor(self, call_id, payload):
        supported_refactorings = ["AddImport", "OrganizeImports", "Rename", "InlineLocal"]
        if payload["refactorType"]["typehint"] in supported_refactorings:
            diff_file = payload["diff"]
            patch_set = fromfile(diff_file)
        if not patch_set:
            self.env.logger.warning("Couldn't parse diff_file: {}"
                                    .format(diff_file))
            return
        self.env.logger.debug("Refactoring get root from: {}"
                              .format(self.refactorings[payload['procedureId']]))
        root = root_as_str_from_abspath(self.refactorings[payload['procedureId']])
        self.env.logger.debug("Refactoring set root: {}"
                              .format(root))
        result = patch_set.apply(0, root)
        if result:
            file = self.refactorings[payload['procedureId']]
            sublime.set_timeout(bind(self.env.editor.reload_file, file), 0)
            self.env.logger.info("Refactoring succeeded, patch file: {}"
                                 .format(diff_file))
            self.env.status_message("Refactoring succeeded")
        else:
            self.env.logger.error("Patch refactoring failed, patch file: {}"
                                  .format(diff_file))
            self.env.status_message("Refactor failed: {}".format(diff_file))

    def show_type(self, call_id, payload):
        tpe = type_to_show(payload)
        self.env.logger.info('Found type {}'.format(tpe))
        content = """
            <body id=show-scope>
                <style>
                    p {
                        margin-top: 0;
                        margin-bottom: 0;
                    }
                    a {
                        font-family: sans-serif;
                        font-size: .7rem;
                    }
                </style>
                <p>%s</p>
                <a href="%s">Copy</a>
            </body>
        """ % (html.escape(tpe, quote=False), html.escape(tpe, quote=True))

        def copy(view, text):
            sublime.set_clipboard(html.unescape(text))
            view.hide_popup()
            sublime.status_message('Type name copied to clipboard')

        sublime.set_timeout(bind(self.env.window.active_view().show_popup,
                                 content,
                                 max_width=512,
                                 on_navigate=lambda x: copy(self.env.window.active_view(), x)), 0)
