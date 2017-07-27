import sublime

import html


# view names
ENSIME_NOTES_VIEW = "Ensime notes"
ENSIME_OUTPUT_VIEW = "Ensime output"
ENSIME_STACK_VIEW = "Ensime stack"
ENSIME_WATCHES_VIEW = "Ensime watches"

# region names
ENSIME_ERROR_OUTLINE_REGION = "ensime-error"
ENSIME_WARNING_OUTLINE_REGION = "ensime-warning"
ENSIME_BREAKPOINT_REGION = "ensime-breakpoint"
ENSIME_DEBUGFOCUS_REGION = "ensime-debugfocus"
ENSIME_STACKFOCUS_REGION = "ensime-stackfocus"

# status bar error format
STATUS_BAR_ERROR = " [Line {line}] {severity} : {msg}"
STATUSGROUP = "ensime_notes"


class Editor(object):
    def __init__(self, window, settings, notes_storage):
        self.w = window
        self.settings = settings
        self.notes_storage = notes_storage
        self.phantom_sets_by_buffer = {}
        self.show_errors = False
        self.suggestions = []
        self.ignore_prefix = None
        self.current_prefix = None

    def colorize(self, view=None):
        if view is None:
            view = self.w.active_view()
        # self.uncolorize(view)
        self.redraw_highlights(view)

    def uncolorize(self, view=None):
        if view is None:
            view = self.w.active_view()
        view.erase_regions(ENSIME_ERROR_OUTLINE_REGION)
        view.erase_regions(ENSIME_WARNING_OUTLINE_REGION)

    def uncolorize_all(self):
        for view in self.w.views():
            self.uncolorize(view)

    def redraw_all_highlights(self):
        for view in self.w.views():
            self.redraw_highlights(view)
        if(self.show_errors):
            self.update_phantoms()

    def redraw_highlights(self, view=None):
        if view is None:
            view = self.w.active_view()
        view.erase_regions(ENSIME_ERROR_OUTLINE_REGION)
        view.erase_regions(ENSIME_WARNING_OUTLINE_REGION)

        relevant_notes = self.notes_storage.for_file(view.file_name())

        # stippled underline the warnings
        warnings = [view.full_line(note.start) for note in relevant_notes if note.severity == "NoteWarn"]
        if self.settings.get("warning_highlight"):
            view.add_regions(
                ENSIME_WARNING_OUTLINE_REGION,
                warnings + view.get_regions(ENSIME_WARNING_OUTLINE_REGION),
                self.settings.get("warning_scope"),
                self.settings.get("warning_icon"),
                sublime.DRAW_NO_FILL)
        # Outline entire errored line
        errors = [view.full_line(note.start) for note in relevant_notes if note.severity == "NoteError"]
        if self.settings.get("error_highlight"):
            view.add_regions(
                ENSIME_ERROR_OUTLINE_REGION,
                errors + view.get_regions(ENSIME_ERROR_OUTLINE_REGION),
                self.settings.get("error_scope"),
                self.settings.get("error_icon"),
                sublime.DRAW_NO_FILL)

    def update_phantoms(self):
        stylesheet = '''
            <style>
                .warn{
                    background-color: color(var(--background) blend(yellow 40%));
                }
                div.error, div.warn {
                    padding: 0.4rem 0 0.4rem 0.7rem;
                    margin: 0.2rem 0;
                    border-radius: 2px;
                }
                div.error span.message, div.warn span.message {
                    padding-right: 0.5rem;
                    font-size: 0.7rem;
                }
                div.error a, div.warn a {
                    text-decoration: inherit;
                    padding: 0.35rem 0.7rem 0.45rem 0.8rem;
                    position: relative;
                    bottom: 0.05rem;
                    border-radius: 0 2px 2px 0;
                    font-weight: bold;
                }
                html.dark div.error a, html.dark div.warn a {
                    background-color: #00000018;
                }
                html.light div.error a, html.light div.warn a {
                    background-color: #ffffff18;
                }
            </style>
        '''
        for file in self.notes_storage.per_file_cache.keys():
            view = self.w.find_open_file(str(file))
            # view is None if no such file is open
            if view:
                buffer_id = view.buffer_id()
                if buffer_id not in self.phantom_sets_by_buffer:
                    phantom_set = sublime.PhantomSet(view, "exec")
                    self.phantom_sets_by_buffer[buffer_id] = phantom_set
                else:
                    phantom_set = self.phantom_sets_by_buffer[buffer_id]

                phantoms = []

                errs = self.notes_storage.for_file(view.file_name())

                for note in errs:
                    if note.severity == "NoteInfo":
                        continue
                    clss = "error" if note.severity == "NoteError" else "warn"
                    phantoms.append(sublime.Phantom(
                        sublime.Region(note.start, note.end),
                        ('<body id=inline-error>' + stylesheet +
                            '<div class=' + clss + '>' +
                            '<span class="message">' + html.escape(note.message, quote=False) + '</span>' +
                            '<a href=hide>' + chr(0x00D7) + '</a></div>' +
                            '</body>'),
                        sublime.LAYOUT_BLOCK,
                        on_navigate=self.on_phantom_navigate))

                phantom_set.update(phantoms)

    def hide_phantoms(self):
        for file in self.notes_storage.per_file_cache.keys():
            view = self.w.find_open_file(str(file))
            if view:
                view.erase_phantoms("exec")
        self.show_errors = False
        self.phantom_sets_by_buffer = {}

    def on_phantom_navigate(self, url):
        self.hide_phantoms()

    def reload_file(self, file):
        view = self.view_for_file(file)
        if view:
            original_size = view.size()
            original_pos = view.sel()[0].begin()
            # Load changes
            view.run_command("revert")

            # Wait until view loaded then move cursor to original position
            def on_load():
                if view.is_loading():
                    # Wait again
                    sublime.set_timeout(on_load, 50)
                else:
                    size_diff = view.size() - original_size
                    new_pos = original_pos + size_diff
                    view.sel().clear()
                    view.sel().add(sublime.Region(new_pos))
                    view.show(new_pos)
                    view.run_command("save")

            on_load()

    def scroll(self, view, line=0):
        if view is not None:
            view.sel().clear()
            line = line - 1 if line > 0 else 0
            offset = view.text_point(line, 0)
            view.sel().add(sublime.Region(offset))
            view.show_at_center(offset)

    def view_for_file(self, file):
        """ Finds the named file in the list of open files, and returns the corresponding View,
        or None if no such file is open."""
        return self.w.find_open_file(file)

    def open_and_scroll(self, file, line):
        view = self.view_for_file(file)
        if view is not None:
            self.w.focus_view(view)
            self.scroll(view, line)
        else:
            print("opening..")
            self.w.open_file("{}:{}:{}".format(file, line, 1), sublime.ENCODED_POSITION)
