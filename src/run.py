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
import cloudinary
import cloudinary.uploader
import re

load_dotenv()
app = Flask(__name__)

#Configuracion para que sea mas entendible el precio
@app.template_filter('formato_precio')
def formato_precio(valor):
    try:
        val = float(valor)
        # Formatea con comas de miles y punto decimal: 1,500,000.00
        # Luego invierte los signos: punto para miles, coma para decimales -> 1.500.000,00
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return valor

# Configuración de Clave Secreta unificada
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-super-segura')
app.config['SECRET_KEY'] = app.secret_key

# Configuración de base de datos
db_uri = os.getenv('DATABASE_URL', 'postgresql://admin_user:admin_pass@db:5432/tienda_db')
if db_uri and db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Evitar error de conexiones caidas
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_timeout': 30,
}
db.init_app(app)

# Configuración automática de Cloudinary mediante la variable de entorno
cloudinary.config(
    cloudinary_url=os.getenv('CLOUDINARY_URL')
)

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
            
def eliminar_archivo_media(url_o_ruta, tipo='imagen'):
    if not url_o_ruta:
        return

    # Si es una URL de Cloudinary
    if "cloudinary.com" in url_o_ruta:
        try:            
            # Obtenemos todo lo que está después de '/upload/'
            partes = url_o_ruta.split('/upload/')
            if len(partes) > 1:
                ruta_despues_upload = partes[1]
                
                # Si empieza con versión tipo 'v12345678/', la removemos
                ruta_sin_version = re.sub(r'^v\d+/', '', ruta_despues_upload)
                
                # Removemos la extensión del final (.jpg, .png, .mp4, etc.)
                public_id = re.sub(r'\.[a-zA-Z0-9]+$', '', ruta_sin_version)
                
                resource_type = "video" if tipo == "video" else "image"
                
                # Llamamos a Cloudinary
                res = cloudinary.uploader.destroy(public_id, resource_type=resource_type, invalidate=True)
                print(f"[CLOUDINARY DELETE] ID: {public_id} | Resultado: {res}")
        except Exception as e:
            print(f"[CLOUDINARY ERROR] al eliminar {url_o_ruta}: {e}")

    # Si es un archivo local
    elif url_o_ruta.startswith('/static/uploads/'):
        nombre_archivo = url_o_ruta.replace('/static/uploads/', '')
        ruta_fisica = os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo)
        if os.path.exists(ruta_fisica):
            try:
                os.remove(ruta_fisica)
                print(f"[LOCAL DELETE] Eliminado: {ruta_fisica}")
            except Exception as e:
                print(f"[LOCAL ERROR] al eliminar archivo local: {e}")

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
                cloudinary_env = os.getenv('CLOUDINARY_URL')
                
                if cloudinary_env:
                    # Subida a Cloudinary (Almacenamiento persistente en la nube)
                    resource_type = "video" if tipo == "video" else "image"
                    resultado = cloudinary.uploader.upload(
                        archivo, 
                        folder="alena_tienda/productos", 
                        resource_type=resource_type
                    )
                    ruta_web = resultado.get("secure_url")
                else:
                    # Subida local (Fallback para desarrollo local)
                    nombre_unico = f"{uuid.uuid4().hex}.{ext}"
                    ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico)
                    archivo.save(ruta_guardado)
                    ruta_web = f"/static/uploads/{nombre_unico}"

                nuevo_media = Media(url_o_ruta=ruta_web, tipo=tipo, producto_id=producto_id)
                db.session.add(nuevo_media)

    # Procesar URL externa si fue proporcionada
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
        if ajuste.logo_url:
            eliminar_archivo_media(ajuste.logo_url, 'imagen')
        ajuste.logo_url = ""
    else:
        logo_file = request.files.get('logo_file')
        if logo_file and logo_file.filename != '':
            # Borrar el logo anterior antes de asignar el nuevo
            if ajuste.logo_url:
                eliminar_archivo_media(ajuste.logo_url, 'imagen')

            if os.getenv('CLOUDINARY_URL'):
                res = cloudinary.uploader.upload(logo_file, folder="alena_tienda/ajustes")
                ajuste.logo_url = res.get("secure_url")
            else:
                tipo, ext = obtener_tipo_archivo(logo_file.filename)
                if ext:
                    nombre_logo = f"logo_{uuid.uuid4().hex}.{ext}"
                    ruta_logo = os.path.join(app.config['UPLOAD_FOLDER'], nombre_logo)
                    logo_file.save(ruta_logo)
                    ajuste.logo_url = f"/static/uploads/{nombre_logo}"

    # 2. Procesar Fondo (Eliminar, Subir Archivo o URL Externa)
    eliminar_fondo = request.form.get('eliminar_fondo')
    if eliminar_fondo:
        if ajuste.imagen_fondo_url:
            eliminar_archivo_media(ajuste.imagen_fondo_url, 'imagen')
        ajuste.imagen_fondo_url = ""
    else:
        imagen_fondo_file = request.files.get('imagen_fondo_file')
        imagen_fondo_url_text = request.form.get('imagen_fondo_url', '').strip()

        if imagen_fondo_file and imagen_fondo_file.filename != '':
            # Borrar el fondo anterior antes de asignar el nuevo
            if ajuste.imagen_fondo_url:
                eliminar_archivo_media(ajuste.imagen_fondo_url, 'imagen')

            if os.getenv('CLOUDINARY_URL'):
                res = cloudinary.uploader.upload(imagen_fondo_file, folder="alena_tienda/ajustes")
                ajuste.imagen_fondo_url = res.get("secure_url")
            else:
                tipo, ext = obtener_tipo_archivo(imagen_fondo_file.filename)
                if ext:
                    nombre_unico = f"bg_{uuid.uuid4().hex}.{ext}"
                    ruta = os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico)
                    imagen_fondo_file.save(ruta)
                    ajuste.imagen_fondo_url = f"/static/uploads/{nombre_unico}"
        elif imagen_fondo_url_text:
            # Si cambia a una URL externa y la anterior era un archivo de Cloudinary/local
            if ajuste.imagen_fondo_url and ajuste.imagen_fondo_url != imagen_fondo_url_text:
                eliminar_archivo_media(ajuste.imagen_fondo_url, 'imagen')
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
    
    # Buscar todos los archivos multimedia asociados al producto
    archivos_media = Media.query.filter_by(producto_id=p.id).all()
    
    # Borrar cada archivo de Cloudinary/local y de la base de datos
    for media in archivos_media:
        eliminar_archivo_media(media.url_o_ruta, media.tipo)
        db.session.delete(media)
    
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
    
    # Elimina el archivo de Cloudinary o local
    eliminar_archivo_media(item_media.url_o_ruta, item_media.tipo)
            
    db.session.delete(item_media)
    db.session.commit()
    return redirect(f"/editar_prod/{producto_id}")

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "t")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
    
    
    


