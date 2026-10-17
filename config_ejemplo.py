"""
============================================================
CONFIGURACION DEL SISTEMA
============================================================
1. Copia este archivo y nombra la copia:  config.py
2. Llena tus datos en config.py
3. config.py NUNCA se sube a GitHub (esta en .gitignore),
   asi tus credenciales quedan solo en tu computadora.
============================================================
"""

# ==================== TELEGRAM ====================
# Token de tu bot (te lo da @BotFather en Telegram)
TOKEN   = "PON_AQUI_TU_TOKEN"
CHAT_ID = "PON_AQUI_TU_CHAT_ID"


# ==================== MODELO (Teachable Machine) ====================
# Archivos que exportas de Teachable Machine (Tensorflow -> Keras)
ARCHIVO_MODELO = "keras_model.h5"
ARCHIVO_LABELS = "labels.txt"

# Nombres EXACTOS de tus 3 clases en Teachable Machine
# (mayusculas/minusculas no importan)
CLASE_VACIO   = "Vacio"     # la entrada sin nadie
CLASE_DUENO   = "Andrei"    # tu
CLASE_EXTERNO = "Externo"   # cualquier otra persona

# Tu nombre, para el mensaje de bienvenida
NOMBRE_DUENO = "Andrei"


# ==================== CAMARA ====================
CAMARA = 0                  # 0 = webcam por defecto (prueba 1 si no anda)
UMBRAL_CONFIANZA = 0.90     # confianza minima del modelo (0.90 = 90%)
FRAMES_CONFIRMA = 10        # frames seguidos para confirmar (menos = mas rapido)
COOLDOWN_CAM_S = 90         # segundos minimos entre alertas de camara
SEGUNDOS_VIDEO_EVIDENCIA = 8


# ==================== RED WIFI ====================
VIGILAR_RED = True          # False para desactivar el monitor de red

# Primeros 3 numeros de la IP de tu(s) red(es). Solo vigila en estas.
# Ej: si tu PC tiene IP 192.168.0.14 -> "192.168.0"
# Puedes poner varias (ej. tu casa y el hotspot de tu celular).
REDES_CASA = ["192.168.0"]

INTERVALO_S = 3             # pausa entre escaneos de red
UMBRAL_AUSENCIA = 3         # escaneos sin ver un equipo para darlo por desconectado

# Dispositivos conocidos: MAC (en minusculas) -> nombre
# La MAC de tu celular: Ajustes -> WiFi -> tu red -> Direccion MAC
CONOCIDOS = {
    # "aa:bb:cc:dd:ee:ff": "TuNombre",
}


# ==================== RESUMEN ====================
HORA_RESUMEN = 21           # hora (0-23) del resumen diario por Telegram
