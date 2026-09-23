# -*- coding: utf-8 -*-
"""PCB 缺陷检测 Web 系统入口"""
from flask import Flask, render_template, request, send_file, session, url_for
import os
import uuid
import json
import time
import cv2

from detector.predict import detect
from report.excel_export import export_report
from database import (init_db, add_record, get_all_records,
                      get_record, delete_record, get_stats)

# ---------- 路径配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
RESULT_DIR = os.path.join(BASE_DIR, "static", "results")
REPORT_PATH = os.path.join(BASE_DIR, "static", "report.xlsx")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

# ---------- Flask 应用 ----------
app = Flask(__name__)
app.secret_key = "pcb_defect_secret_key_2024"

init_db()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/detect", methods=["POST"])
def detect_route():
    files = request.files.getlist("images")
    files = [f for f in files if f and f.filename]

    if not files:
        return render_template("index.html", error="请至少上传一张图片")

    conf = float(request.form.get("conf", 0.25))

    results = []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".bmp"]:
            continue
        fname = f"{uuid.uuid4().hex}{ext}"

        src_path = os.path.join(UPLOAD_DIR, fname)
        f.save(src_path)

        try:
            img, defects = detect(src_path, conf=conf)
        except Exception as e:
            print(f"[detect] 处理失败 {f.filename}: {e}")
            continue

        out_path = os.path.join(RESULT_DIR, fname)
        cv2.imwrite(out_path, img)

        src_url = url_for("static", filename=f"uploads/{fname}")
        result_url = url_for("static", filename=f"results/{fname}")

        add_record(
            image_name=f.filename,
            src_url=src_url,
            result_url=result_url,
            defects=defects,
            conf=conf,
        )

        results.append({
            "name": f.filename,
            "src": src_url,
            "result": result_url,
            "defects": defects,
        })

    session["last_results"] = json.dumps(
        [{"name": r["name"], "defects": r["defects"]} for r in results],
        ensure_ascii=False
    )

    total = sum(len(r["defects"]) for r in results)
    return render_template("result.html",
                           results=results,
                           total=total,
                           conf=conf)


@app.route("/redetect", methods=["POST"])
def redetect():
    """重新检测接口"""
    data = request.get_json()
    src_url = data.get("src", "")
    conf = float(data.get("conf", 0.25))

    if not src_url.startswith("/static/"):
        return {"error": "非法路径"}, 400

    rel = src_url.replace("/static/", "", 1)
    src_path = os.path.join(BASE_DIR, "static", rel)

    if not os.path.exists(src_path):
        return {"error": "原图不存在"}, 404

    try:
        img, defects = detect(src_path, conf=conf)
    except Exception as e:
        return {"error": str(e)}, 500

    fname = f"re_{int(time.time() * 1000)}_{os.path.basename(src_path)}"
    out_path = os.path.join(RESULT_DIR, fname)
    cv2.imwrite(out_path, img)

    return {
        "result": url_for("static", filename=f"results/{fname}"),
        "defects": defects,
        "count": len(defects),
        "conf": conf,
    }


@app.route("/export")
def export():
    data = json.loads(session.get("last_results", "[]"))
    if not data:
        return "没有可导出的数据，请先检测", 400

    export_report(data, REPORT_PATH)
    return send_file(REPORT_PATH,
                     as_attachment=True,
                     download_name="PCB_缺陷检测报告.xlsx")


# ================= 历史记录 =================

@app.route("/history")
def history():
    records = get_all_records()
    stats = get_stats()
    for r in records:
        r["defects"] = json.loads(r["defects_json"])
    return render_template("history.html", records=records, stats=stats)


@app.route("/history/delete/<int:record_id>", methods=["POST"])
def history_delete(record_id):
    delete_record(record_id)
    return {"ok": True}


@app.route("/history/export/<int:record_id>")
def history_export(record_id):
    record = get_record(record_id)
    if not record:
        return "记录不存在", 404

    defects = json.loads(record["defects_json"])
    data = [{"name": record["image_name"], "defects": defects}]

    export_report(data, REPORT_PATH)
    return send_file(REPORT_PATH,
                     as_attachment=True,
                     download_name=f"PCB_检测报告_{record_id}.xlsx")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)