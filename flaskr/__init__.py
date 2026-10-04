"""flaskr v1: 익명 게시판 (pallets/flask examples/tutorial 기반, BSD-3-Clause).

v1에는 서명 키·로그인이 없다(장부 32). 환경별 값은 전부 환경변수로 받는다(config.py).
"""

from __future__ import annotations

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from flaskr import config, db


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(test_config if test_config is not None else config.load())

    # 온프렘 0/0(끔), 클라우드 2/1(ALB → nginx → WAS)
    x_for, x_proto = app.config["PROXY_FIX_X_FOR"], app.config["PROXY_FIX_X_PROTO"]
    if x_for or x_proto:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=x_for, x_proto=x_proto)

    db.init_app(app)

    from flaskr import health

    app.register_blueprint(health.bp)
    for module in _feature_modules():
        app.register_blueprint(module.bp)
    app.add_url_rule("/", endpoint="index")
    return app


def _feature_modules() -> list:
    """기능 Blueprint 목록. 새 기능(v2~)은 flaskr/<기능>.py에 bp를 두고 여기에 한 줄 추가한다."""
    from flaskr import blog, uploads

    return [blog, uploads]
