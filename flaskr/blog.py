"""v1 익명 게시판: 목록·글쓰기만.

출처: pallets/flask examples/tutorial/flaskr/blog.py @d73fa1c (BSD-3-Clause, Copyright 2010 Pallets).

원본 대비 변경: 로그인·사용자·메시지 기능 제거(v1은 쿠키 상태를 쓰지 않음, 장부 32),
수정·삭제 라우트 제거, 쿼리는 text() + 이름 자리표시자.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, redirect, render_template, request, url_for
from sqlalchemy import text

from flaskr.db import get_engine

bp = Blueprint("blog", __name__)


def _as_datetime(value):
    # SQLite(개발 PC)는 문자열, MySQL은 datetime으로 돌려준다.
    return datetime.fromisoformat(value) if isinstance(value, str) else value


@bp.route("/")
def index():
    with get_engine().begin() as conn:
        rows = conn.execute(
            text("SELECT id, title, body, created FROM post ORDER BY created DESC, id DESC")
        ).mappings()
        posts = [{**row, "created": _as_datetime(row["created"])} for row in rows]
    return render_template("blog/index.html", posts=posts)


@bp.route("/create", methods=("GET", "POST"))
def create():
    error = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "")
        if not title:
            error = "Title is required."
        elif len(title) > 200:
            error = "Title is too long."
        else:
            with get_engine().begin() as conn:
                conn.execute(
                    text("INSERT INTO post (title, body) VALUES (:title, :body)"),
                    {"title": title, "body": body},
                )
            return redirect(url_for("blog.index"))
    return render_template("blog/create.html", error=error)
