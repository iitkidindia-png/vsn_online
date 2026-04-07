from flask import Flask, render_template, request, redirect, session, send_file
import sqlite3
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

app = Flask(__name__)
app.secret_key = "secret123"

def db():
    return sqlite3.connect("school.db")

# INIT DB
conn = db()
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS admin (u TEXT, p TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY, name TEXT, class TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS books(id INTEGER PRIMARY KEY, name TEXT, class TEXT, price REAL, barcode TEXT, stock INT)")
c.execute("CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, student_id INT, book_id INT, qty INT, total REAL, date TEXT)")

try:
    conn.execute("ALTER TABLE students ADD COLUMN roll TEXT")
except:
    pass

try:
    conn.execute("ALTER TABLE books ADD COLUMN publisher TEXT")
except:
    pass

try:
    conn.execute("ALTER TABLE sales ADD COLUMN invoice_no TEXT")
except:
    pass

c.execute("""
CREATE TABLE IF NOT EXISTS cart(
    id INTEGER PRIMARY KEY,
    student_id INT,
    book_id INT,
    book_name TEXT,
    qty INT,
    price REAL
)
""")

if not c.execute("SELECT * FROM admin").fetchone():
    c.execute("INSERT INTO admin VALUES ('admin','admin123')")

conn.commit()
conn.close()

# LOGIN
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = request.form['u']
        p = request.form['p']
        if db().execute("SELECT * FROM admin WHERE u=? AND p=?", (u,p)).fetchone():
            session['user']=u
            return redirect('/')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# HOME (Dashboard)
@app.route('/')
def home():
    if 'user' not in session:
        return redirect('/login')

    conn = db()
    total = conn.execute("SELECT SUM(total) FROM sales").fetchone()[0] or 0
    books = conn.execute("SELECT * FROM books").fetchall()
    students = conn.execute("SELECT * FROM students").fetchall()
    cart = conn.execute("""
    SELECT cart.student_id, cart.book_id, students.name, cart.book_name, cart.qty, cart.price
    FROM cart
    JOIN students ON students.id = cart.student_id
""").fetchall()
    cart_total = sum([c[4] * c[5] for c in cart])
    conn.close()

    clear_ui = session.pop('clear_cart_ui', False)

    return render_template(
        "index.html",
        students=students,
        books=books,
        cart=cart,
        cart_total=cart_total,
        total=total,
        clear_ui=clear_ui
    )

# ADD STUDENT
@app.route('/add_student', methods=['POST'])
def add_student():
    conn = db()
    conn.execute("INSERT INTO students(name,class,roll) VALUES (?,?,?)",
                 (request.form['name'], request.form['class'], request.form['roll']))
    conn.commit()
    conn.close()
    return redirect('/')

# ADD BOOK
@app.route('/add_book', methods=['POST'])
def add_book():
    conn = db()
    conn.execute("""
        INSERT INTO books(name,class,price,barcode,stock,publisher)
        VALUES (?,?,?,?,?,?)
    """, (
        request.form['name'],
        request.form['class'],
        request.form['price'],
        request.form['barcode'],
        request.form['stock'],
        request.form['publisher']
    ))
    conn.commit()
    conn.close()
    return redirect('/')

# SELL
@app.route('/sell', methods=['POST'])
def sell():
    barcode = request.form['barcode']
    qty = int(request.form['qty'])
    student = request.form['student']

    cur = db().cursor()
    b = cur.execute("SELECT id,price,stock FROM books WHERE barcode=?", (barcode,)).fetchone()

    if not b:
        return "Invalid barcode"

    id, price, stock = b
    if stock < qty:
        return "Low stock"

    total = price * qty

    cur.execute("UPDATE books SET stock=stock-? WHERE id=?", (qty,id))
    cur.execute("INSERT INTO sales(student_id,book_id,qty,total,date) VALUES (?,?,?,?,?)",
                (student,id,qty,total,datetime.now().strftime('%Y-%m-%d')))

    db().commit()

    return redirect(f'/invoice/{student}')

# PDF INVOICE
import random

@app.route('/invoice/<int:sid>')
def invoice(sid):
    conn = db()
    cur = conn.cursor()

    student = cur.execute("SELECT name FROM students WHERE id=?", (sid,)).fetchone()
    student_name = student[0]

    invoice_no = session.get('invoice_no')

    data = cur.execute("""
        SELECT books.name, sales.qty, sales.total, sales.date
        FROM sales
        JOIN books ON books.id = sales.book_id
        WHERE sales.invoice_no=?
    """, (invoice_no,)).fetchall()
    total = sum([d[2] for d in data])
    conn.close()

    return render_template(
    "invoice.html",
    data=data,
    student_name=student_name,
    total=sum([d[2] for d in data]),
    invoice_no=invoice_no,
    today=datetime.now().strftime('%d-%m-%Y'),
    sid=sid
)

@app.route('/invoice_pdf/<int:sid>')
def invoice_pdf(sid):
    conn = db()
    data = conn.execute("SELECT * FROM sales WHERE student_id=?", (sid,)).fetchall()

    file = f"invoice_{sid}.pdf"
    doc = SimpleDocTemplate(file)

    table = Table([["BookID","Qty","Total","Date"]] + [[d[2], d[3], d[4], d[5]] for d in data])
    doc.build([table])

    return send_file(file, as_attachment=True)

# REPORT

@app.route('/report')
def report():
    conn = db()
    cur = conn.cursor()

    class_filter = request.args.get('class')
    student_filter = request.args.get('student')
    date_filter = request.args.get('date')

    query = """
    SELECT students.name, students.class, sales.date, books.name,
           sales.qty, sales.total, sales.invoice_no, students.id
    FROM sales
    JOIN students ON students.id = sales.student_id
    JOIN books ON books.id = sales.book_id
    WHERE 1=1
    """

    params = []

    if class_filter:
        query += " AND students.class=?"
        params.append(class_filter)

    if student_filter:
        query += " AND students.id=?"
        params.append(student_filter)

    if date_filter:
        query += " AND DATE(sales.date)=?"
        params.append(date_filter)

    query += " ORDER BY sales.date DESC"

    report = cur.execute(query, params).fetchall()

    students = conn.execute("SELECT id,name FROM students").fetchall()

    conn.close()

    return render_template('report.html', report=report, students=students)



@app.route('/invoice_pdf_by_no/<path:invoice_no>')
def invoice_pdf_by_no(invoice_no):

    # ✅ REGISTER FONT (₹ FIX)
    pdfmetrics.registerFont(TTFont('Noto', 'static/fonts/NotoSans-Regular.ttf'))

    conn = db()
    cur = conn.cursor()

    data = cur.execute("""
        SELECT books.name, sales.qty, books.price, sales.total, sales.date,
               students.name, students.class, students.roll
        FROM sales
        JOIN books ON books.id = sales.book_id
        JOIN students ON students.id = sales.student_id
        WHERE sales.invoice_no=?
    """, (invoice_no,)).fetchall()

    if not data:
        return "No data found"

    student_name = data[0][5]
    student_class = data[0][6]
    student_roll = data[0][7]
    date = data[0][4]

    grand_total = sum([d[3] for d in data])

    # ✅ FILE PATH
    folder = os.path.join(os.getcwd(), "invoices")
    os.makedirs(folder, exist_ok=True)

    safe_invoice = invoice_no.replace("/", "_")
    file_path = os.path.join(folder, f"{safe_invoice}.pdf")

    styles = getSampleStyleSheet()

    # ✅ CUSTOM STYLE WITH FONT
    normal = ParagraphStyle(name='Normal', fontName='Noto', fontSize=10, alignment=1)
    title = ParagraphStyle(name='Title', fontName='Noto', fontSize=16, alignment=1)

    elements = []

    # ================= HEADER WITH LOGO =================
        
    logo_path = "static/logo.png"

    header_data = []

    # ✅ LOGO (CENTER)
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=70, height=70)
        header_data.append([logo])

    # ✅ SCHOOL NAME
    header_data.append([Paragraph("<b>VIVEKANANDA SHIKSHA NIKETAN</b>", title)])

    # ✅ ADDRESS
    header_data.append([Paragraph("Nalichara, Ambassa, Dhalai, Tripura", normal)])

    header = Table(header_data, colWidths=[500])

    header.setStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ])

    elements.append(header)
    elements.append(Spacer(1, 10))

    # ================= META =================
    meta = Table([
        ["Invoice No:", invoice_no, "Date:", date],
        ["Student:", student_name, "Class:", student_class],
        ["Roll No:", student_roll, "", ""]
    ], colWidths=[90, 180, 60, 120])

    meta.setStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])

    elements.append(meta)
    elements.append(Spacer(1, 15))

    # ================= ITEMS =================
    table_data = [["Sl No", "Book Name", "Qty", "Price", "Total"]]

    for i, d in enumerate(data, start=1):
        table_data.append([
            i,
            d[0],
            d[1],
            f"₹ {d[2]:.2f}",
            f"₹ {d[3]:.2f}"
        ])

    table = Table(table_data, colWidths=[50, 220, 60, 80, 80])

    table.setStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Noto'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

        ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
        ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
        ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),

        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])

    elements.append(table)
    elements.append(Spacer(1, 15))

    # ================= TOTAL =================
    total_table = Table([
        ["", "", "Grand Total", f"₹ {grand_total:.2f}"]
    ], colWidths=[50, 220, 140, 80])

    total_table.setStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Noto'),
        ('GRID', (2, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('ALIGN', (3, 0), (3, 0), 'RIGHT'),
        ('BACKGROUND', (2, 0), (-1, -1), colors.lightgrey),
    ])

    elements.append(total_table)
    elements.append(Spacer(1, 40))

    # ================= FOOTER =================
    footer = Table([
        ["Customer Signature", "", "Authorized Signature"]
    ], colWidths=[180, 100, 180])

    footer.setStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Noto'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
    ])

    elements.append(footer)

    # ================= BUILD =================
    doc = SimpleDocTemplate(file_path, pagesize=A4)
    doc.build(elements)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"{invoice_no}.pdf"
    )


# STUDENTS VIEW
@app.route('/students')
def students():
    s = db().execute("SELECT * FROM students").fetchall()
    return render_template('students.html', students=s)

# API (FOR ANDROID)
@app.route('/api/books')
def api_books():
    data = db().execute("SELECT * FROM books").fetchall()
    return {"books": data}


# ================= ADD TO CART =================
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    barcode = request.form['barcode']
    qty = int(request.form['qty'])
    student_id = request.form['student']

    conn = db()
    cur = conn.cursor()

    book = cur.execute("SELECT id,name,price FROM books WHERE barcode=?", (barcode,)).fetchone()

    if not book:
        return "Invalid barcode"

    book_id, book_name, price = book

    # ✅ STORE STUDENT IN SESSION (IMPORTANT)
    session['student_id'] = student_id

    # ✅ CHECK IF ALREADY IN CART → INCREASE QTY
    existing = cur.execute(
    "SELECT * FROM cart WHERE book_id=? AND student_id=?",
    (book_id, student_id)
).fetchone()

    if existing:
        cur.execute(
    "UPDATE cart SET qty = qty + ? WHERE book_id=? AND student_id=?",
    (qty, book_id, student_id)
)
    else:
        cur.execute("""
            INSERT INTO cart(student_id, book_id, book_name, qty, price)
            VALUES (?,?,?,?,?)
        """, (student_id, book_id, book_name, qty, price))

    conn.commit()
    conn.close()

    return redirect('/')


@app.route('/remove_from_cart/<int:student_id>/<int:book_id>')
def remove_from_cart(student_id, book_id):
    conn = db()
    conn.execute("DELETE FROM cart WHERE student_id=? AND book_id=?",
                 (student_id, book_id))
    conn.commit()
    conn.close()
    return redirect('/')

# ================= CHECKOUT =================
@app.route('/checkout')
def checkout():
    conn = db()
    cur = conn.cursor()

    student_id = session.get('student_id')

    if not student_id:
        return "No student selected"

    # GET STUDENT NAME
    student = cur.execute("SELECT name FROM students WHERE id=?", (student_id,)).fetchone()
    student_name = student[0]

    cart_items = cur.execute("""
    SELECT book_id, qty, price
    FROM cart
    WHERE student_id=?
""", (student_id,)).fetchall()
    
    invoice_no = generate_invoice_no()
    session['invoice_no'] = invoice_no
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    session['invoice_time'] = now
    
    for item in cart_items:
        book_id = item[0]
        qty = int(item[1])
        price = float(item[2])
        total = qty * price

        # SAVE SALE
        cur.execute("""
    INSERT INTO sales(student_id, book_id, qty, total, date, invoice_no)
    VALUES (?,?,?,?,?,?)
""", (student_id, book_id, qty, total, now, invoice_no))

        # UPDATE STOCK
        cur.execute("UPDATE books SET stock = stock - ? WHERE id=?", (qty, book_id))

    # CLEAR CART AFTER CHECKOUT
    cur.execute("DELETE FROM cart WHERE student_id=?", (student_id,))

    conn.commit()
    conn.close()
# ✅ CLEAR STUDENT SESSION
    session.pop('student_id', None)

    return redirect(f"/invoice/{student_id}")

#➕➖ Increase / Decrease Quantity
@app.route('/inc_qty/<int:student_id>/<int:book_id>')
def inc_qty(student_id, book_id):
    conn = db()
    conn.execute("""
        UPDATE cart SET qty = qty + 1 
        WHERE student_id=? AND book_id=?
    """, (student_id, book_id))
    conn.commit()
    conn.close()
    return redirect('/')


@app.route('/dec_qty/<int:student_id>/<int:book_id>')
def dec_qty(student_id, book_id):
    conn = db()
    conn.execute("""
        UPDATE cart SET qty = CASE 
            WHEN qty > 1 THEN qty - 1 
            ELSE 1 
        END
        WHERE student_id=? AND book_id=?
    """, (student_id, book_id))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/book_report')
def book_report():
    conn = db()

    class_filter = request.args.get('class')

    if class_filter:
        books = conn.execute("""
            SELECT books.name, books.class, books.publisher, books.price, books.stock,
                   IFNULL(SUM(sales.qty),0) as sold,
                   IFNULL(SUM(sales.total),0) as revenue
            FROM books
            LEFT JOIN sales ON books.id = sales.book_id
            WHERE books.class=?
            GROUP BY books.id
        """, (class_filter,)).fetchall()
    else:
        books = conn.execute("""
            SELECT books.name, books.class, books.publisher, books.price, books.stock,
                   IFNULL(SUM(sales.qty),0) as sold,
                   IFNULL(SUM(sales.total),0) as revenue
            FROM books
            LEFT JOIN sales ON books.id = sales.book_id
            GROUP BY books.id
        """).fetchall()

    conn.close()

    return render_template('book_report.html', books=books)

def generate_invoice_no():
    conn = db()
    cur = conn.cursor()

    year = datetime.now().year

    last = cur.execute("""
        SELECT invoice_no FROM sales
        WHERE invoice_no LIKE ?
        ORDER BY id DESC LIMIT 1
    """, (f"VSN/{year}/%",)).fetchone()

    if last:
        last_no = int(last[0].split("/")[-1])
        new_no = last_no + 1
    else:
        new_no = 1

    conn.close()

    return f"VSN/{year}/{str(new_no).zfill(4)}"

if __name__ == '__main__':
    app.run(debug=True)
