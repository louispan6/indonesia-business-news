import traceback
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

from main import run_daily_job


app = Flask(__name__)
BEIJING_TZ = timezone(timedelta(hours=8), name="UTC+08:00")


@app.get("/")
def health_check():
    return jsonify(
        {
            "status": "ok",
            "service": "openclaw-indonesia-news",
            "time": datetime.now(BEIJING_TZ).isoformat(timespec="seconds"),
        }
    )


@app.route("/run-news", methods=["GET", "POST"])
def run_news():
    fetch_only = request.args.get("fetch_only", "").lower() in {"1", "true", "yes"}

    try:
        result = run_daily_job(fetch_only=fetch_only)
        return jsonify(
            {
                "success": True,
                "result": result,
            }
        )
    except Exception as exc:
        app.logger.exception("run_daily_job failed")
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            ),
            500,
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
