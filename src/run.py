from flask import Flask, render_template, request, url_for, redirect, session, flash
from models import db, Producto, Usuario, Media, Especificacion, AjusteWhatsApp
import os
import uuid
import time
import urllib.parse
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()
app = Flask(__name__)

# Configuración de Clave Secreta unificada
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-super-segura')
app.config['SECRET_KEY'] = app.secret_key

# Configuración de base de datos
db_uri = os.getenv('DATABASE_URL', 'postgresql://admin_user:admin_pass@db:5432/tienda_db')
if db_uri and db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# Límites de archivos y directorios de carga
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024
CARPETA_UPLOADS = os.path.join('src', 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = CARPETA_UPLOADS
os.makedirs(CARPETA_UPLOADS, exist_ok=True)
EXTENSIONES_IMAGENES = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EXTENSIONES_VIDEOS = {'mp4', 'webm', 'ogg'}

# Limitador de peticiones (Rate Limiter)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["300 per day", "100 per hour"],
    storage_uri="memory://"
)

# Inicialización segura de BD y Creación/Actualización de Admin
with app.app_context():
    print("----------------------------------------")
    print("Iniciando conexión con la Base de Datos...")
    print("----------------------------------------")
    conectado = False
    intentos = 10
    while not conectado and intentos > 0:
        try:
            db.create_all()
            conectado = True
            print("¡Tablas verificadas/creadas exitosamente!")
        except Exception as e:
            intentos -= 1
            print(f"Reintentando conexión ({intentos} intentos restantes)... Error: {e}")
            time.sleep(2)

    if conectado:
        admin_user = str(os.getenv("ADMIN_USERNAME", "admin")).strip()
        admin_pass = str(os.getenv("ADMIN_PASSWORD", "admin123")).strip()
        
        admin = Usuario.query.filter_by(nombreusuario=admin_user).first()
        
        if not admin:
            clave_encriptada = generate_password_hash(admin_pass)
            admin = Usuario(nombreusuario=admin_user, contraseña_hash=clave_encriptada, es_admin=True)
            db.session.add(admin)
            db.session.commit()
            print(f"-> Usuario administrador '{admin_user}' creado exitosamente.")
        else:
            admin.contraseña_hash = generate_password_hash(admin_pass)
            admin.es_admin = True
            db.session.commit()
            print(f"-> Credenciales de '{admin_user}' actualizadas desde el entorno.")

def obtener_tipo_archivo(nombre_archivo):
    ext = nombre_archivo.rsplit('.', 1)[-1].lower() if '.' in nombre_archivo else ''
    if ext in EXTENSIONES_IMAGENES:
        return 'imagen', ext
    elif ext in EXTENSIONES_VIDEOS:
        return 'video', ext
    return None, None
    
def guardar_archivos_producto(producto_id, archivos_locales, url_externa):
    for archivo in archivos_locales:
        if archivo and archivo.filename != '':
            tipo, ext = obtener_tipo_archivo(archivo.filename)
            
            if tipo and ext:
                nombre_unico = f"{uuid.uuid4().hex}.{ext}"
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico)
                archivo.save(ruta_guardado)

                ruta_web = f"/static/uploads/{nombre_unico}"
                nuevo_media = Media(url_o_ruta=ruta_web, tipo=tipo, producto_id=producto_id)
                db.session.add(nuevo_media)

    # Procesar URL externa si existe
    if url_externa and url_externa.strip() != '':
        tipo_url = 'video' if any(e in url_externa.lower() for e in ['.mp4', 'youtube', 'vimeo']) else 'imagen'
        nuevo_media_url = Media(url_o_ruta=url_externa.strip(), tipo=tipo_url, producto_id=producto_id)
        db.session.add(nuevo_media_url)

    db.session.commit()

# Context Processor global para base.html
@app.context_processor
def inject_ajustes():
    ajuste_wa = AjusteWhatsApp.query.first()
    return dict(ajuste_wa=ajuste_wa)

# RUTAS PÚBLICAS 

@app.route("/")
def prueba():
    query_buscar = request.args.get('q', '').strip()
    query_categoria = request.args.get('categoria', '').strip()
    query = Producto.query
    if query_buscar:
        query = query.filter(Producto.nombre.ilike(f"%{query_buscar}%"))
    if query_categoria:
        query = query.filter(Producto.categoria == query_categoria)
    productos = query.all()
    categoria_tuples = db.session.query(Producto.categoria).distinct().all()
    categorias = [c[0] for c in categoria_tuples if c[0]]
    return render_template('index.html', productos=productos, categorias=categorias, q_actual=query_buscar, cat_actual=query_categoria)

@app.route("/producto/<int:producto_id>")
def detalle_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    
    ajuste_wa = AjusteWhatsApp.query.first()
    numero_wa = ajuste_wa.numero if (ajuste_wa and ajuste_wa.numero) else "5491122334455"
    plantilla_msj = ajuste_wa.mensaje_template if (ajuste_wa and ajuste_wa.mensaje_template) else "¡Hola! Me interesó el producto '{producto}' (${precio}). ¿Tienen stock?"

    mensaje_formateado = plantilla_msj.replace("{producto}", producto.nombre)
    mensaje_formateado = mensaje_formateado.replace("{precio}", f"{producto.precio:.2f}")
    mensaje_url = urllib.parse.quote(mensaje_formateado)

    wa_link = f"https://wa.me/{numero_wa}?text={mensaje_url}"
    return render_template('detalle.html', producto=producto, wa_link=wa_link)

# RUTAS DE ADMINISTRACIÓN

@app.route("/admin/login", methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def inicio_admin():
    if request.method == "POST":
        usuario_ingresado = str(request.form.get('nombreusuario', '') or '').strip()
        clave_ingresada = str(request.form.get('contraseña', '') or '').strip()

        u = Usuario.query.filter_by(nombreusuario=usuario_ingresado).first()

        if u and check_password_hash(u.contraseña_hash, clave_ingresada):
            session['usuario_id'] = u.id
            session['es_admin'] = u.es_admin
            return redirect("/admin")
        
        flash("Usuario o contraseña incorrectos. Por favor, verificá tus datos.", "danger")
        return redirect("/admin/login")

    return render_template("login.html")

@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template("login.html", bloqueado=True), 429

@app.route("/admin")
def admin_dashboard():
    if not session.get('es_admin'):
        return redirect('/admin/login')

    productos = Producto.query.all()
    ajuste_wa = AjusteWhatsApp.query.first()
    return render_template('admin_dashboard.html', productos=productos, ajuste_wa=ajuste_wa)

@app.route("/admin/logout")
def logout():
    session.clear()  
    return redirect("/admin/login")  

@app.route("/admin/ajustes_wa", methods=['POST'])
def guardar_ajustes_wa():
    if not session.get('es_admin'):
        return redirect('/admin/login')
    
    ajuste = AjusteWhatsApp.query.first()
    if not ajuste:
        ajuste = AjusteWhatsApp()
        db.session.add(ajuste)

    ajuste.numero = request.form.get('numero', '').strip()
    ajuste.mensaje_template = request.form.get('mensaje_template', '').strip()
    ajuste.nombre_tienda = request.form.get('nombre_tienda', 'Alena Mdza').strip()
    ajuste.color_primario = request.form.get('color_primario', '#00a859').strip()
    ajuste.color_fondo = request.form.get('color_fondo', '#f4f6f8').strip()
    
    # 1. Procesar Logo (Eliminar o Subir Nuevo)
    eliminar_logo = request.form.get('eliminar_logo')
    if eliminar_logo:
        ajuste.logo_url = ""
    else:
        logo_file = request.files.get('logo_file')
        if logo_file and logo_file.filename != '':
            tipo, ext = obtener_tipo_archivo(logo_file.filename)
            if ext:
                nombre_logo = f"logo_{uuid.uuid4().hex}.{ext}"
                ruta_logo = os.path.join(app.config['UPLOAD_FOLDER'], nombre_logo)
                logo_file.save(ruta_logo)
                ajuste.logo_url = f"/static/uploads/{nombre_logo}"

    # 2. Procesar Fondo (Eliminar, Subir Archivo o URL Externa)
    eliminar_fondo = request.form.get('eliminar_fondo')
    if eliminar_fondo:
        ajuste.imagen_fondo_url = ""
    else:
        imagen_fondo_file = request.files.get('imagen_fondo_file')
        imagen_fondo_url_text = request.form.get('imagen_fondo_url', '').strip()

        if imagen_fondo_file and imagen_fondo_file.filename != '':
            tipo, ext = obtener_tipo_archivo(imagen_fondo_file.filename)
            if ext:
                nombre_unico = f"bg_{uuid.uuid4().hex}.{ext}"
                ruta = os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico)
                imagen_fondo_file.save(ruta)
                ajuste.imagen_fondo_url = f"/static/uploads/{nombre_unico}"
        elif imagen_fondo_url_text:
            ajuste.imagen_fondo_url = imagen_fondo_url_text

    db.session.commit()
    return redirect('/admin')

@app.route("/a_v_productos", methods=['GET', 'POST'])
def agregar():
    if not session.get('es_admin'):
        return redirect('/admin/login')

    if request.method == 'POST':
        p = Producto(
            nombre=request.form.get('nombre'),
            precio=float(request.form.get('precio', 0)),
            categoria=request.form.get('categoria'),
            stock=int(request.form.get('stock', 1)),
            descripcion=request.form.get('descripcion')
        )
        db.session.add(p)
        db.session.commit()

        claves = request.form.getlist('espec_clave[]')
        valores = request.form.getlist('espec_valor[]')
        for c, v in zip(claves, valores):
            if c.strip() and v.strip():
                db.session.add(Especificacion(clave=c.strip(), valor=v.strip(), producto_id=p.id))

        archivos = request.files.getlist('archivos_locales')
        url_ext = request.form.get('imagen_url')
        guardar_archivos_producto(p.id, archivos, url_ext)

        return redirect("/admin")

    return render_template('nuevo_producto.html')
    
@app.route("/eliminar_prod/<int:id>", methods=['POST'])
def eliminar(id):
    if not session.get('es_admin'):
        return redirect('/admin/login')
    p = Producto.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    return redirect("/admin")

@app.route("/editar_prod/<int:producto_id>", methods=['GET', 'POST'])
def editar_producto(producto_id):
    if not session.get('es_admin'):
        return redirect('/admin/login')

    producto = Producto.query.get_or_404(producto_id)

    if request.method == 'POST':
        producto.nombre = request.form.get('nombre')
        producto.categoria = request.form.get('categoria')
        producto.precio = float(request.form.get('precio', 0))
        producto.stock = int(request.form.get('stock', 1))
        producto.descripcion = request.form.get('descripcion')

        Especificacion.query.filter_by(producto_id=producto.id).delete()
        claves = request.form.getlist('espec_clave[]')
        valores = request.form.getlist('espec_valor[]')
        for c, v in zip(claves, valores):
            if c.strip() and v.strip():
                db.session.add(Especificacion(clave=c.strip(), valor=v.strip(), producto_id=producto.id))

        db.session.commit()

        archivos = request.files.getlist('archivos_locales')
        url_ext = request.form.get('imagen_url')
        guardar_archivos_producto(producto.id, archivos, url_ext)

        return redirect('/admin')

    return render_template('editar_producto.html', producto=producto)

@app.route("/eliminar_media/<int:media_id>", methods=['POST'])
def eliminar_media(media_id):
    if not session.get('es_admin'):
        return redirect('/admin/login')
    
    item_media = Media.query.get_or_404(media_id)
    producto_id = item_media.producto_id
    
    if item_media.url_o_ruta.startswith('/static/uploads/'):
        nombre_archivo = item_media.url_o_ruta.replace('/static/uploads/', '')
        ruta_fisica = os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo)
        if os.path.exists(ruta_fisica):
            os.remove(ruta_fisica)
            
    db.session.delete(item_media)
    db.session.commit()
    return redirect(f"/editar_prod/{producto_id}")

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "t")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
    
    
    
    


