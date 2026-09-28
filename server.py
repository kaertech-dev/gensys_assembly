import os
from flask import Flask, request, jsonify, send_from_directory
from gensys_assembly import check_operator, insert_assembly, insert_ems_main, get_fail_count_for_serial, build_fail_serial_num, is_fail_limit_reached, MAX_FAIL_TESTS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    emp = str(payload.get("employee", "")).strip()
    shift = str(payload.get("shift", "A")).strip() or "A"

    if not emp:
        return jsonify({"ok": False, "message": "Enter employee number."}), 400

    try:
        authorized = check_operator(emp)
    except Exception as exc:
        return jsonify({"ok": False, "message": f"DB error: {exc}"}), 500

    if not authorized:
        return jsonify({"ok": False, "message": f"Employee '{emp}' not in database."}), 401

    return jsonify({"ok": True, "employee": emp, "shift": shift})


@app.route("/api/record/pass", methods=["POST"])
def record_pass():
    payload = request.get_json(silent=True) or {}
    serial_num = str(payload.get("serial_num", "")).strip()
    po_num = str(payload.get("po_num", "")).strip()
    operator = str(payload.get("operator", "")).strip()
    shift = str(payload.get("shift", "A")).strip() or "A"
    customer_sn = str(payload.get("customer_sn", "")).strip()

    if not serial_num:
        return jsonify({"ok": False, "message": "Scan the serial number first."}), 400
    if not po_num:
        return jsonify({"ok": False, "message": "Enter the PO number before saving."}), 400
    if not operator:
        return jsonify({"ok": False, "message": "Login required before saving."}), 401

    try:
        record = {
            "serial_num": serial_num,
            "po_num": po_num,
            "operator_en": operator,
            "shift": shift,
            "date_time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "customer_sn": customer_sn,
            "test_rep": 1,
            "remarks": " ",
            "status": 1,
        }
        insert_assembly(record)

        ems_main_record = {
            "serial_num": serial_num,
            "po_num": po_num,
            "soldering": 0,
            "cleaning": 0,
            "vi": 0,
            "progtest": 0,
            "insulation": 0,
            "assembly": 1,
            "lasermarking": 0,
            "fvi": 0,
            "packing": 0,
            "packaging": 0,
        }
        insert_ems_main(ems_main_record)
        return jsonify({"ok": True, "message": f"✓ Saved | Serial: {serial_num}"})
    except Exception as exc:
        return jsonify({"ok": False, "message": f"DB error: {exc}"}), 500


@app.route("/api/record/fail", methods=["POST"])
def record_fail():
    payload = request.get_json(silent=True) or {}
    serial_num = str(payload.get("serial_num", "")).strip()
    po_num = str(payload.get("po_num", "")).strip()
    operator = str(payload.get("operator", "")).strip()
    shift = str(payload.get("shift", "A")).strip() or "A"
    customer_sn = str(payload.get("customer_sn", "")).strip()
    reason = str(payload.get("reason", "")).strip()

    if not serial_num:
        return jsonify({"ok": False, "message": "Scan the serial number first."}), 400
    if not po_num:
        return jsonify({"ok": False, "message": "Enter the PO number before saving the fail."}), 400
    if not operator:
        return jsonify({"ok": False, "message": "Login required before saving fail."}), 401
    if not reason:
        return jsonify({"ok": False, "message": "Enter a failure reason before saving."}), 400

    try:
        fail_count = get_fail_count_for_serial(serial_num)
        if is_fail_limit_reached(fail_count):
            return jsonify({
                "ok": False,
                "message": f"Max fail reached for {serial_num}. Please endorse to FA team.",
                "max_reached": True,
            }), 400

        next_fail_num = fail_count + 1
        fail_serial = build_fail_serial_num(serial_num, fail_count)

        record = {
            "serial_num": fail_serial,
            "po_num": po_num,
            "operator_en": operator,
            "shift": shift,
            "date_time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "customer_sn": customer_sn,
            "test_rep": next_fail_num,
            "remarks": reason,
            "status": 0,
        }
        insert_assembly(record)

        ems_main_record = {
            "serial_num": serial_num,
            "po_num": po_num,
            "soldering": 0,
            "cleaning": 0,
            "vi": 0,
            "progtest": 0,
            "insulation": 0,
            "assembly": 1,
            "lasermarking": 0,
            "fvi": 0,
            "packing": 0,
            "packaging": 0,
        }
        insert_ems_main(ems_main_record)

        return jsonify({
            "ok": True,
            "message": f"✓ Fail saved | Serial: {fail_serial} | Test fail: {next_fail_num}/{MAX_FAIL_TESTS}",
            "serial": fail_serial,
            "fail_count": next_fail_num,
        })
    except Exception as exc:
        return jsonify({"ok": False, "message": f"DB error: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5057, debug=False)
