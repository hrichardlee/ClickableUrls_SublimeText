import sublime
import sublime_plugin
import webbrowser
import threading
import os.path


class UrlHighlighter(sublime_plugin.EventListener):
    # Thanks Jeff Atwood http://www.codinghorror.com/blog/2008/10/the-problem-with-urls.html
    # ^ that up here is a URL that should be matched
    URL_REGEX = "\\bhttps?://[-A-Za-z0-9+&@#/%?=~_()|!:,.;']*[-A-Za-z0-9+&@#/%=~_(|]"
    DEFAULT_MAX_URLS = 200
    SETTINGS_FILENAME = 'ClickableUrls.sublime-settings'

    urls_for_view = {}
    scopes_for_view = {}
    ignored_views = []
    browser = None
    highlight_semaphore = threading.Semaphore()

    def on_activated(self, view):
        self.update_url_highlights(view, False)

    # Blocking handlers for ST2
    def on_load(self, view):
        if sublime.version() < '3000':
            self.update_url_highlights(view, False)

    def on_modified(self, view):
        if sublime.version() < '3000':
            self.update_url_highlights(view, False)

    # Async listeners for ST3
    def on_load_async(self, view):
        self.update_url_highlights_async(view, False)

    def on_modified_async(self, view):
        self.update_url_highlights_async(view, False)

    def on_close(self, view):
        for map in [self.urls_for_view, self.scopes_for_view, self.ignored_views]:
            if view.id() in map:
                del map[view.id()]

    """The logic entry point. Find all URLs in view, store and highlight them"""
    def update_url_highlights(self, view, force):
        settings = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME)
        if not force and not settings.get('auto_find_urls', True):
            return

        should_highlight_urls = settings.get('highlight_urls', True)
        max_url_limit = settings.get('max_url_limit', UrlHighlighter.DEFAULT_MAX_URLS)
        file_folder_regex = settings.get('file_folder_regex', '')
        combined_regex = '({})|({})'.format(UrlHighlighter.URL_REGEX, file_folder_regex) if file_folder_regex else UrlHighlighter.URL_REGEX

        if view.id() in UrlHighlighter.ignored_views:
            return

        urls = view.find_all(combined_regex)

        # Avoid slowdowns for views with too much URLs
        if len(urls) > max_url_limit:
            print("UrlHighlighter: ignoring view with %u URLs" % len(urls))
            UrlHighlighter.ignored_views.append(view.id())
            return

        UrlHighlighter.urls_for_view[view.id()] = urls

        should_highlight_urls = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('highlight_urls', True)
        if (should_highlight_urls):
            self.highlight_urls(view, urls)

    """Same as update_url_highlights, but avoids race conditions with a
    semaphore."""
    def update_url_highlights_async(self, view, force):
        UrlHighlighter.highlight_semaphore.acquire()
        try:
            self.update_url_highlights(view, force)
        finally:
            UrlHighlighter.highlight_semaphore.release()

    """Creates a set of regions from the intersection of urls and scopes,
    underlines all of them."""
    def highlight_urls(self, view, urls):
        # We need separate regions for each lexical scope for ST to use a proper color for the underline
        scope_map = {}
        for url in urls:
            scope_name = view.scope_name(url.a)
            scope_map.setdefault(scope_name, []).append(url)

        for scope_name in scope_map:
            self.underline_regions(view, scope_name, scope_map[scope_name])

        self.update_view_scopes(view, scope_map.keys())

    """Apply underlining with provided scope name to provided regions.
    Uses the empty region underline hack for Sublime Text 2 and native
    underlining for Sublime Text 3."""
    def underline_regions(self, view, scope_name, regions):
        if sublime.version() >= '3019':
            # in Sublime Text 3, the regions are just underlined
            view.add_regions(
                u'clickable-urls ' + scope_name,
                regions,
                scope_name,
                flags=sublime.DRAW_NO_FILL|sublime.DRAW_NO_OUTLINE|sublime.DRAW_SOLID_UNDERLINE)
        else:
            # in Sublime Text 2, the 'empty region underline' hack is used
            char_regions = [sublime.Region(pos, pos) for region in regions for pos in range(region.a, region.b)]
            view.add_regions(
                u'clickable-urls ' + scope_name,
                char_regions,
                scope_name,
                sublime.DRAW_EMPTY_AS_OVERWRITE)

    """Store new set of underlined scopes for view. Erase underlining from
    scopes that were used but are not anymore."""
    def update_view_scopes(self, view, new_scopes):
        old_scopes = UrlHighlighter.scopes_for_view.get(view.id(), None)
        if old_scopes:
            unused_scopes = set(old_scopes) - set(new_scopes)
            for unused_scope_name in unused_scopes:
                view.erase_regions(u'clickable-urls ' + unused_scope_name)

        UrlHighlighter.scopes_for_view[view.id()] = new_scopes

class FindUrlsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        UrlHighlighter().update_url_highlights_async(self.view, True)


def open_url(url, view):
    if os.path.isfile(url):
        view.window().open_file(url)
    else:
        browser = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('clickable_urls_browser')
        try:
            webbrowser.get(browser).open(url, autoraise=True)
        except(webbrowser.Error):
            sublime.error_message('Failed to open browser. See "Customizing the browser" in the README.')

class OpenUrlUnderCursorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.id() in UrlHighlighter.urls_for_view:
            selection = self.view.sel()[0]
            if selection.empty():
                selection = next((url for url in UrlHighlighter.urls_for_view[self.view.id()] if url.contains(selection)), None)
                if not selection:
                    return
            url = self.view.substr(selection)
            open_url(url, self.view)


class OpenAllUrlsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.id() in UrlHighlighter.urls_for_view:
            for url in set([self.view.substr(url_region) for url_region in UrlHighlighter.urls_for_view[self.view.id()]]):
                open_url(url, view)