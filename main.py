# -*- coding: utf-8 -*-
"""
نظام الحضور والغياب - مديرية الموارد المائية (نسخة الموبايل)
التشغيل على الكمبيوتر للتجربة:  flet run main.py
البناء كتطبيق أندرويد:          flet build apk
"""
import os
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta

import flet as ft

ORG = "مديرية الموارد المائية"
CREDIT = "برمجة:م. مهند النابلسي"
STATUSES = ["حاضر", "غائب", "إجازة", "مهمة رسمية", "مرضية"]
LATE_AFTER = "08:30"  # الدخول بعد هذا الوقت يُحتسب تأخيراً
WEEKDAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
REP_HEADER = ["الرقم الوظيفي", "الاسم", "حضور", "تأخير", "غياب", "إجازة", "مهمة", "مرضية"]
COLORS = {
    "حاضر": ft.Colors.GREEN_700, "غائب": ft.Colors.RED_700,
    "إجازة": ft.Colors.BLUE_700, "مهمة رسمية": ft.Colors.PURPLE_700,
    "مرضية": ft.Colors.ORANGE_800, "غير مسجل": ft.Colors.GREY_600,
}

# على الأندرويد تُحفظ قاعدة البيانات في مجلد التطبيق الدائم
DATA_DIR = os.environ.get("FLET_APP_STORAGE_DATA") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "attendance.db")


def db_connect():
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("""CREATE TABLE IF NOT EXISTS employees(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_no TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        section TEXT,
        job TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS attendance(
        emp_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        status TEXT NOT NULL,
        check_in TEXT,
        check_out TEXT,
        PRIMARY KEY(emp_id, day),
        FOREIGN KEY(emp_id) REFERENCES employees(id) ON DELETE CASCADE)""")
    con.commit()
    return con


def main(page: ft.Page):
    page.title = ORG
    page.rtl = True
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    con = db_connect()
    state = {"tab": 0, "q": "", "day": date.today(), "month": date.today().replace(day=1)}
    R = ft.TextAlign.RIGHT

    def toast(msg):
        page.open(ft.SnackBar(ft.Text(msg)))

    def confirm(title, text, on_yes):
        def yes(e):
            page.close(dlg)
            on_yes()
        dlg = ft.AlertDialog(
            title=ft.Text(title), content=ft.Text(text),
            actions=[ft.TextButton("إلغاء", on_click=lambda e: page.close(dlg)),
                     ft.ElevatedButton("تأكيد", on_click=yes)])
        page.open(dlg)

    def search_box(on_change):
        return ft.TextField(hint_text="بحث بالاسم أو الرقم أو القسم", prefix_icon=ft.Icons.SEARCH,
                            value=state["q"], dense=True, text_align=R, on_change=on_change)

    def like():
        q = f"%{state['q']}%"
        return (q, q, q)

    # ------------------------------------------------------------ الموظفون
    def emp_dialog(emp_id=None):
        row = ("", "", "", "")
        if emp_id:
            row = con.execute("SELECT emp_no,name,section,job FROM employees WHERE id=?",
                              (emp_id,)).fetchone()
        f_no = ft.TextField(label="الرقم الوظيفي", value=row[0], text_align=R)
        f_name = ft.TextField(label="الاسم", value=row[1], text_align=R)
        f_sec = ft.TextField(label="القسم", value=row[2] or "", text_align=R)
        f_job = ft.TextField(label="المسمى الوظيفي", value=row[3] or "", text_align=R)

        def save(e):
            vals = [f.value.strip() for f in (f_no, f_name, f_sec, f_job)]
            f_no.error_text = None if vals[0] else "مطلوب"
            f_name.error_text = None if vals[1] else "مطلوب"
            if not (vals[0] and vals[1]):
                dlg.update()
                return
            try:
                if emp_id:
                    con.execute("UPDATE employees SET emp_no=?,name=?,section=?,job=? WHERE id=?",
                                vals + [emp_id])
                else:
                    con.execute("INSERT INTO employees(emp_no,name,section,job) VALUES(?,?,?,?)", vals)
                con.commit()
            except sqlite3.IntegrityError:
                f_no.error_text = "الرقم الوظيفي مستخدم مسبقاً"
                dlg.update()
                return
            page.close(dlg)
            show()

        def delete(e):
            page.close(dlg)

            def do():
                con.execute("DELETE FROM employees WHERE id=?", (emp_id,))
                con.commit()
                show()
            confirm("حذف الموظف", "سيتم حذف الموظف مع كامل سجل حضوره. متأكد؟", do)

        actions = []
        if emp_id:
            actions.append(ft.TextButton("حذف", on_click=delete,
                                         style=ft.ButtonStyle(color=ft.Colors.RED_700)))
        actions += [ft.TextButton("إلغاء", on_click=lambda e: page.close(dlg)),
                    ft.ElevatedButton("حفظ", on_click=save)]
        dlg = ft.AlertDialog(title=ft.Text("تعديل موظف" if emp_id else "إضافة موظف"),
                             content=ft.Column([f_no, f_name, f_sec, f_job], tight=True,
                                               scroll=ft.ScrollMode.AUTO),
                             actions=actions)
        page.open(dlg)

    def import_dialog(e=None):
        box = ft.TextField(multiline=True, min_lines=6, max_lines=10, text_align=R,
                           hint_text="1001, أحمد علي, قسم الصيانة, فني\n1002, سعاد محمد, الحسابات, محاسب")

        def do_import(e):
            added = skipped = 0
            for line in (box.value or "").splitlines():
                cells = [c.strip() for c in re.split(r"[\t,;،]", line)]
                if len(cells) < 2 or not cells[0] or cells[0] in ("emp_no", "الرقم الوظيفي"):
                    continue
                cells = (cells + ["", ""])[:4]
                try:
                    con.execute("INSERT INTO employees(emp_no,name,section,job) VALUES(?,?,?,?)", cells)
                    added += 1
                except sqlite3.IntegrityError:
                    skipped += 1
            con.commit()
            page.close(dlg)
            show()
            toast(f"تمت إضافة {added} موظف، وتخطي {skipped} (مكرر)")

        dlg = ft.AlertDialog(
            title=ft.Text("استيراد موظفين"),
            content=ft.Column([
                ft.Text("الصق القائمة: سطر لكل موظف (رقم، اسم، قسم، مسمى) "
                        "- يمكن نسخها مباشرة من Excel.", size=12),
                box], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("إلغاء", on_click=lambda e: page.close(dlg)),
                     ft.ElevatedButton("استيراد", on_click=do_import)])
        page.open(dlg)

    def emp_view():
        lv = ft.ListView(expand=True)
        total = con.execute("SELECT COUNT(*) FROM employees").fetchone()[0]

        def rows():
            data = con.execute(
                "SELECT id, emp_no, name, section, job FROM employees "
                "WHERE name LIKE ? OR emp_no LIKE ? OR section LIKE ? ORDER BY name", like()).fetchall()
            return [ft.ListTile(
                leading=ft.Icon(ft.Icons.PERSON), title=ft.Text(r[2]),
                subtitle=ft.Text(" • ".join(x for x in (r[1], r[3], r[4]) if x)),
                on_click=lambda e, i=r[0]: emp_dialog(i)) for r in data]

        def on_search(e):
            state["q"] = e.control.value.strip()
            lv.controls = rows()
            lv.update()

        lv.controls = rows()
        return ft.Column([
            ft.Row([ft.ElevatedButton("إضافة موظف", icon=ft.Icons.ADD, on_click=lambda e: emp_dialog()),
                    ft.OutlinedButton("استيراد", icon=ft.Icons.UPLOAD, on_click=import_dialog)]),
            search_box(on_search),
            ft.Text(f"إجمالي الموظفين: {total}", size=12),
            lv], expand=True)

    # ------------------------------------------------------------ الحضور اليومي
    def att_dialog(emp_id, name):
        day = state["day"].isoformat()
        old = con.execute("SELECT check_in, check_out FROM attendance WHERE emp_id=? AND day=?",
                          (emp_id, day)).fetchone()
        t_in = ft.TextField(label="الدخول", value=(old and old[0]) or "08:00",
                            width=120, text_align=ft.TextAlign.CENTER)
        t_out = ft.TextField(label="الخروج", value=(old and old[1]) or "15:00",
                             width=120, text_align=ft.TextAlign.CENTER)

        def set_status(st):
            tin = tout = ""
            if st == "حاضر":
                try:
                    datetime.strptime(t_in.value, "%H:%M")
                    datetime.strptime(t_out.value, "%H:%M")
                except ValueError:
                    t_in.error_text = "HH:MM"
                    t_out.error_text = "HH:MM"
                    dlg.update()
                    return
                tin, tout = t_in.value, t_out.value
            con.execute("INSERT OR REPLACE INTO attendance(emp_id,day,status,check_in,check_out) "
                        "VALUES(?,?,?,?,?)", (emp_id, day, st, tin, tout))
            con.commit()
            page.close(dlg)
            show()

        def clear(e):
            con.execute("DELETE FROM attendance WHERE emp_id=? AND day=?", (emp_id, day))
            con.commit()
            page.close(dlg)
            show()

        dlg = ft.AlertDialog(
            title=ft.Text(name),
            content=ft.Column(
                [ft.Row([t_in, t_out])]
                + [ft.ElevatedButton(s, width=250, on_click=lambda e, s=s: set_status(s))
                   for s in STATUSES]
                + [ft.TextButton("مسح التسجيل", on_click=clear)],
                tight=True, scroll=ft.ScrollMode.AUTO))
        page.open(dlg)

    def pick_date(e):
        def changed(ev):
            state["day"] = ev.control.value.date()
            show()
        page.open(ft.DatePicker(value=datetime.combine(state["day"], datetime.min.time()),
                                first_date=datetime(2020, 1, 1), last_date=datetime(2040, 12, 31),
                                on_change=changed))

    def shift_day(n):
        state["day"] += timedelta(days=n)
        show()

    def mark_rest_present(e):
        day = state["day"].isoformat()

        def do():
            con.execute("INSERT OR IGNORE INTO attendance(emp_id,day,status,check_in,check_out) "
                        "SELECT id,?,'حاضر','08:00','15:00' FROM employees", (day,))
            con.commit()
            show()
        confirm("تسجيل الباقي حاضر",
                "سيتم تسجيل كل الموظفين غير المسجلين لهذا اليوم كـ (حاضر) 08:00 - 15:00.", do)

    def att_view():
        day = state["day"].isoformat()
        lv = ft.ListView(expand=True)

        def fetch():
            return con.execute(
                "SELECT e.id, e.emp_no, e.name, e.section, COALESCE(a.status,'غير مسجل'), "
                "COALESCE(a.check_in,''), COALESCE(a.check_out,'') "
                "FROM employees e LEFT JOIN attendance a ON a.emp_id=e.id AND a.day=? "
                "WHERE e.name LIKE ? OR e.emp_no LIKE ? OR e.section LIKE ? ORDER BY e.name",
                (day,) + like()).fetchall()

        def rows():
            out = []
            for r in fetch():
                sub = " • ".join(x for x in (r[1], r[3]) if x)
                if r[5]:
                    sub += f"  ({r[5]} - {r[6]})"
                out.append(ft.ListTile(
                    title=ft.Text(r[2]), subtitle=ft.Text(sub),
                    trailing=ft.Container(ft.Text(r[4], color=ft.Colors.WHITE, size=12),
                                          bgcolor=COLORS[r[4]], border_radius=12,
                                          padding=ft.padding.symmetric(horizontal=10, vertical=4)),
                    on_click=lambda e, i=r[0], n=r[2]: att_dialog(i, n)))
            return out

        def on_search(e):
            state["q"] = e.control.value.strip()
            lv.controls = rows()
            lv.update()

        c = Counter(r[0] for r in con.execute(
            "SELECT COALESCE(a.status,'غير مسجل') FROM employees e "
            "LEFT JOIN attendance a ON a.emp_id=e.id AND a.day=?", (day,)))
        summary = "  |  ".join(f"{s}: {c.get(s, 0)}" for s in STATUSES + ["غير مسجل"])
        lv.controls = rows()
        label = f"{WEEKDAYS[state['day'].weekday()]}  {day}"
        return ft.Column([
            ft.Row([ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda e: shift_day(-1)),
                    ft.TextButton(label, icon=ft.Icons.CALENDAR_MONTH, on_click=pick_date),
                    ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda e: shift_day(1)),
                    ft.IconButton(ft.Icons.DONE_ALL, tooltip="تسجيل غير المسجلين حاضر",
                                  on_click=mark_rest_present)],
                   alignment=ft.MainAxisAlignment.CENTER),
            ft.Text(summary, size=12),
            search_box(on_search),
            lv], expand=True)

    # ------------------------------------------------------------ التقارير
    def rep_data():
        m = state["month"].strftime("%Y-%m")
        rows = con.execute(
            "SELECT e.emp_no, e.name, "
            "SUM(a.status='حاضر'), SUM(a.status='حاضر' AND a.check_in > ?), "
            "SUM(a.status='غائب'), SUM(a.status='إجازة'), "
            "SUM(a.status='مهمة رسمية'), SUM(a.status='مرضية') "
            "FROM employees e LEFT JOIN attendance a "
            "ON a.emp_id=e.id AND substr(a.day,1,7)=? "
            "GROUP BY e.id ORDER BY e.name", (LATE_AFTER, m)).fetchall()
        return [[r[0], r[1]] + [x or 0 for x in r[2:]] for r in rows]

    def shift_month(n):
        m = state["month"]
        state["month"] = ((m + timedelta(days=32)) if n > 0 else (m - timedelta(days=1))).replace(day=1)
        show()

    def copy_report(e):
        m = state["month"].strftime("%Y-%m")
        lines = [f"{ORG} - تقرير الحضور والغياب لشهر {m}", "\t".join(REP_HEADER)]
        lines += ["\t".join(str(x) for x in r) for r in rep_data()]
        lines += ["", CREDIT]
        page.set_clipboard("\n".join(lines))
        toast("تم نسخ التقرير - الصقه في Excel أو واتساب أو البريد")

    def rep_view():
        data = rep_data()
        lv = ft.ListView(expand=True)

        def rows():
            q = state["q"]
            return [ft.ListTile(
                title=ft.Text(r[1]),
                subtitle=ft.Text(f"{r[0]}  |  حضور {r[2]} • تأخير {r[3]} • غياب {r[4]} • "
                                 f"إجازة {r[5]} • مهمة {r[6]} • مرضية {r[7]}", size=12))
                for r in data if q in r[1] or q in str(r[0])]

        def on_search(e):
            state["q"] = e.control.value.strip()
            lv.controls = rows()
            lv.update()

        lv.controls = rows()
        return ft.Column([
            ft.Row([ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda e: shift_month(-1)),
                    ft.Text(state["month"].strftime("%Y-%m"), size=18, weight=ft.FontWeight.BOLD),
                    ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda e: shift_month(1)),
                    ft.ElevatedButton("نسخ التقرير", icon=ft.Icons.COPY, on_click=copy_report)],
                   alignment=ft.MainAxisAlignment.CENTER),
            search_box(on_search),
            lv], expand=True)

    # ------------------------------------------------------------ الإطار العام
    views = [emp_view, att_view, rep_view]
    body = ft.Container(expand=True, padding=8)

    def show(e=None):
        body.content = views[state["tab"]]()
        page.update()

    def on_nav(e):
        state["tab"] = e.control.selected_index
        state["q"] = ""
        show()

    page.appbar = ft.AppBar(title=ft.Text(ORG), center_title=True,
                            bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE)
    page.navigation_bar = ft.NavigationBar(
        selected_index=0, on_change=on_nav,
        destinations=[ft.NavigationBarDestination(icon=ft.Icons.PEOPLE, label="الموظفون"),
                      ft.NavigationBarDestination(icon=ft.Icons.FACT_CHECK, label="الحضور"),
                      ft.NavigationBarDestination(icon=ft.Icons.ASSESSMENT, label="التقارير")])
    footer = ft.Container(ft.Text(CREDIT, size=12, weight=ft.FontWeight.BOLD,
                                  color=ft.Colors.BLUE_900),
                          alignment=ft.alignment.center, padding=4)
    page.add(ft.SafeArea(content=ft.Column([body, footer], expand=True, spacing=0), expand=True))
    show()


ft.app(target=main)
