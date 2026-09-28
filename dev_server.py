"""Dev-сервер для правки интерфейса в обычном браузере.

Запуск: python dev_server.py, затем http://127.0.0.1:8765/index.html?dev=1
Отдаёт ui/ и эмулирует мост pywebview через POST /api/<метод>.
Диалоги файлов в браузере недоступны: отчёт печатается в консоль сервера.
"""

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import calc

UI = Path(__file__).parent / "ui"
STORE = {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(UI), **kw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        name = self.path.rsplit("/", 1)[-1]
        if name == "compute":
            out = calc.compute(body)
        elif name == "defaults":
            out = dict(calc.DEFAULTS)
        elif name == "version":
            out = calc.__version__
        elif name == "set_title":
            out = True
        elif name == "load_settings":
            out = STORE.get("s", {})
        elif name == "save_settings":
            STORE["s"] = body
            out = True
        elif name == "export_report":
            print(calc.report(calc.compute(body)))
            out = None
        elif name == "save_config":
            STORE["cfg"] = calc.normalize(body)
            out = "(dev) в памяти сервера"
        elif name == "open_config":
            out = STORE.get("cfg")
        else:
            self.send_error(404)
            return
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("http://127.0.0.1:8765/index.html?dev=1")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
