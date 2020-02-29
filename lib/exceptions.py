class BrowserUnavailable(Exception):
    pass


class LibraryNotSupported(Exception):
    pass


class LibraryPageNotValid(Exception):
    pass


class LibraryNotConfigured(Exception):
    pass


class BooksListUnavailable(Exception):
    pass


class ProfileNotFoundError(Exception):
    pass


class ShelvesScrapeError(Exception):
    pass


class BooksCollectError(Exception):
    pass
