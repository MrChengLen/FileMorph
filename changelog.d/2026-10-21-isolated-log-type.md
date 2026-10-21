### Changed — The log names the error type of a failed conversion child

When a table conversion, PDF compression or PDF → TXT child process fails
unexpectedly, the server log now names the child's error type (the exception
class name) at warning level, next to the generic error the route logs. As for
every logged error, the error's text stays out of the log.
