"""A tiny recorder of what the server does for one request.

Every step has a layer (API / AI / OS / DBMS / FILE / CACHE), a title and a detail. The payment endpoints return the
steps as `trace`, and the web app shows them in its "Under the hood" panel - so a viva audience can *watch* locks,
transactions, caching and the audit log work while a payment goes through.
"""
import time


class Trace:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.steps: list = []

    def add(self, layer: str, title: str, detail: str = "") -> "Trace":
        self.steps.append({"t_ms": round((time.perf_counter() - self.t0) * 1000, 1), "layer": layer,
                           "title": title, "detail": detail})
        return self
