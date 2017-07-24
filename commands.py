import sublime_plugin
import sublime

import sys
from functools import partial as bind

from core import EnsimeWindowCommand, EnsimeTextCommand
from env import getEnvironment
from launcher import EnsimeLauncher
from client import EnsimeClient
from util import Util
from outgoing import (TypeCheckFilesReq,
                      SymbolAtPointReq,
                      ImportSuggestionsReq,
                      OrganiseImports,
                      RenameRefactorDesc,
                      InlineLocalRefactorDesc,
                      CompletionsReq,
                      TypeAtPointReq,
                      DocUriAtPointReq)


class EnsimeStartup(EnsimeWindowCommand):
    def is_enabled(self):
        return bool(self.env and not self.env.is_running())

    def run(self):
        try:
            self.env.recalc()
        except Exception:
            typ, value, traceback = sys.exc_info()
            self.env.error_message("Got an error : {t}\n{val}"
                                   .format(t=typ, val=value))
        else:
            launcher = EnsimeLauncher(self.env.config)
            self.env.client = EnsimeClient(self.env, launcher)
            self.env.client.setup()


class EnsimeShutdown(EnsimeWindowCommand):
    def is_enabled(self):
        return bool(self.env and self.env.is_running())

    def run(self):
        self.env.shutdown()


class EnsimeToggleErrors(EnsimeWindowCommand):
    def is_enabled(self):
        return bool(self.env and
                    self.env.is_connected() and
                    len(self.env.window.views()) > 0 and
                    self.env.client.analyzer_ready)

    def run(self):
        if self.env.editor.show_errors:
            self.env.editor.hide_phantoms()
        else:
            self.env.editor.show_errors = True
            self.env.editor.redraw_all_highlights()


class EnsimeEventListener(sublime_plugin.EventListener):
    def on_load(self, view):
        file = view.file_name()
        if not (Util.is_scala(file) or Util.is_java(file)):
            return
        env = getEnvironment(view.window())
        if env and env.is_connected() and env.client.analyzer_ready:
            TypeCheckFilesReq([view.file_name()]).run_in(env, async=True)

    def on_post_save(self, view):
        file = view.file_name()
        if not (Util.is_scala(file) or Util.is_java(file)):
            return
        env = getEnvironment(view.window())
        if env and env.is_connected() and env.client.analyzer_ready:
            TypeCheckFilesReq([view.file_name()]).run_in(env, async=True)

    def on_query_completions(self, view, prefix, locations):
        file = view.file_name()
        if not (Util.is_scala(file) or Util.is_java(file)):
            return
        env = getEnvironment(view.window())
        if env and env.is_connected() and env.client.indexer_ready:
            if (env.editor.ignore_prefix and prefix.startswith(env.editor.ignore_prefix)):
                return []
            else:
                env.editor.ignore_prefix = None

            if (env.editor.current_prefix is not None and prefix == env.editor.current_prefix):
                env.editor.current_prefix = None
                if view.is_popup_visible():
                    view.hide_popup()
                env.logger.info("Search for more suggestions either completed or was cancelled.")
                return env.editor.suggestions

            contents = (view.substr(sublime.Region(0, view.size())) if view.is_dirty()
                        else None)
            response = CompletionsReq(locations[0],
                                      view.file_name(),
                                      contents,
                                      max_results=5).run_in(env, async=False)

            if response is None:
                return ([],
                        sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
                env.editor.ignore_prefix = prefix
            else:
                if len(env.editor.suggestions) > 1:
                    CompletionsReq(locations[0], view.file_name(), contents).run_in(env, async=True)
                    view.show_popup("Please wait while we query for more suggestions.",
                                    sublime.HIDE_ON_MOUSE_MOVE | sublime.COOPERATE_WITH_AUTO_COMPLETE)
                return (env.editor.suggestions,
                        sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)


class EnsimeGoToDefinition(EnsimeTextCommand):
    def is_enabled(self):
        env = getEnvironment(sublime.active_window())
        return bool(env and env.is_connected() and env.client.indexer_ready)

    def run(self, edit, target=None):
        env = getEnvironment(self.view.window())
        view = self.view
        if len(view.sel()) <= 2:
            contents = (view.substr(sublime.Region(0, view.size())) if view.is_dirty()
                        else None)
            pos = int(target or view.sel()[0].begin())
            SymbolAtPointReq(view.file_name(),
                             contents,
                             pos).run_in(env, async=True)
        else:
            env.status_message("You have multiple cursors. Ensime is confused :/")


class EnsimeAddImport(EnsimeTextCommand):
    def is_enabled(self):
        env = getEnvironment(sublime.active_window())
        return bool(env and env.is_connected() and env.client.indexer_ready)

    def run(self, edit, target=None):
        env = getEnvironment(self.view.window())
        pos = int(target or self.view.sel()[0].begin())
        if self.view.is_dirty():
            self.view.run_command('save')
        ImportSuggestionsReq(pos,
                             self.view.file_name(),
                             self.view.substr(self.view.word(pos))).run_in(env, async=True)


class EnsimeOrganiseImports(EnsimeTextCommand):
    def is_enabled(self):
        env = getEnvironment(sublime.active_window())
        return bool(env and env.is_connected() and env.client.indexer_ready)

    def run(self, edit):
        env = getEnvironment(self.view.window())
        if self.view.is_dirty():
            self.view.run_command('save')
        OrganiseImports(self.view.file_name()).run_in(env, async=True)


class EnsimeRename(EnsimeTextCommand):
    def is_enabled(self):
        env = getEnvironment(sublime.active_window())
        return bool(env and env.is_connected() and env.client.indexer_ready)

    def run(self, edit):
        env = getEnvironment(self.view.window())
        regions = [r for r in self.view.sel()]
        if len(regions) == 1:
            region = regions[0]
            if region.begin() == region.end():
                env.status_message('Please select a region to extract the symbol to rename')
            else:
                def make_request(arg):
                    RenameRefactorDesc(arg,
                                       region.begin(),
                                       region.end(),
                                       self.view.file_name()).run_in(env, async=True)
                self.view.window().show_input_panel("Rename to : ",
                                                    '',
                                                    make_request, None, None)
        else:
            env.status_message('Select a single region to extract the symbol to rename')


class EnsimeInlineLocal(EnsimeTextCommand):
    def is_enabled(self):
        env = getEnvironment(sublime.active_window())
        return bool(env and env.is_connected() and env.client.indexer_ready)

    def run(self, edit, target=None):
        env = getEnvironment(self.view.window())
        pos = int(target or self.view.sel()[0].begin())
        word = self.view.substr(self.view.word(pos))
        InlineLocalRefactorDesc(pos,
                                pos + len(word),
                                self.view.file_name()).run_in(env, async=True)


class EnsimeShowType(EnsimeTextCommand):
    def is_enabled(self):
        env = getEnvironment(sublime.active_window())
        return bool(env and env.is_connected() and env.client.indexer_ready)

    def run(self, edit, target=None):
        env = getEnvironment(self.view.window())
        view = self.view
        if len(view.sel()) <= 1:
            contents = (view.substr(sublime.Region(0, view.size())) if view.is_dirty()
                        else None)
            pos = int(target or view.sel()[0].begin())
            TypeAtPointReq(view.file_name(),
                           contents,
                           pos).run_in(env, async=True)
        else:
            env.status_message("You have multiple cursors. Ensime is confused :/")


class EnsimeBrowseDocAtPoint(EnsimeTextCommand):
    def is_enabled(self):
        env = getEnvironment(sublime.active_window())
        return bool(env and env.is_connected() and env.client.indexer_ready)

    def run(self, edit, target=None):
        env = getEnvironment(self.view.window())
        view = self.view
        if len(view.sel()) <= 1:
            contents = (view.substr(sublime.Region(0, view.size())) if view.is_dirty()
                        else None)
            pos = int(target or view.sel()[0].begin())
            DocUriAtPointReq(view.file_name(),
                             contents,
                             pos).run_in(env, async=True)
        else:
            env.status_message("You have multiple cursors. Ensime is confused :/")
