"""Writing section: essay + Part 2 options."""
from flask import Blueprint, render_template

from app.services.writing import get_writing_context

bp = Blueprint("writing", __name__)


@bp.route("/writing")
def writing():
    ctx = get_writing_context()
    return render_template("writing.html", **ctx)
