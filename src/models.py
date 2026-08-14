from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Producto(db.Model):
    __tablename__ = 'producto'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    precio = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(50), nullable=True)
    stock = db.Column(db.Integer, default=1)  # Campo Stock
    descripcion = db.Column(db.Text, nullable=True)  # Descripción detallada

    multimedia = db.relationship('Media', backref='producto', cascade="all, delete-orphan", lazy=True)
    especificaciones = db.relationship('Especificacion', backref='producto', cascade="all, delete-orphan", lazy=True)

class Media(db.Model):
    __tablename__ = 'media'
    id = db.Column(db.Integer, primary_key=True)
    url_o_ruta = db.Column(db.String(500), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)

class Especificacion(db.Model):
    __tablename__ = 'especificacion'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(100), nullable=False)  # Ej: Color, Talle
    valor = db.Column(db.String(100), nullable=False)  # Ej: Azul, XL
    producto_id = db.Column(db.Integer, db.ForeignKey('producto.id'), nullable=False)

class AjusteWhatsApp(db.Model):
    __tablename__ = 'ajuste_whatsapp'
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(50), default="5491122334455")
    mensaje_template = db.Column(db.Text, default="¡Hola! Me interesó el producto '{producto}' (${precio}). ¿Tienen stock?")
    
    # Campos de personalización visual
    nombre_tienda = db.Column(db.String(100), default="Alena Mdza")
    logo_url = db.Column(db.String(500), default="")
    color_primario = db.Column(db.String(20), default="#00a859")
    color_fondo = db.Column(db.String(20), default="#f4f6f8")
    imagen_fondo_url = db.Column(db.String(500), default="")

class Usuario(db.Model):
    __tablename__ = 'usuario'
    id = db.Column(db.Integer, primary_key=True)
    nombreusuario = db.Column(db.String(50), unique=True, nullable=False)
    contraseña_hash = db.Column(db.String(255), nullable=False)
    es_admin = db.Column(db.Boolean, default=False)