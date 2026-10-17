# Sistema de seguridad de vivienda con IA

Proyecto final de ISW-221 Inteligencia Artificial.
Andrei Nagel Zelaya · Ingeniería Mecatrónica · UCB "San Pablo", Santa Cruz.

## Entregables

- 📄 **Artículo científico:** [DOCUMENTS/Articulo_Seguridad_Vivienda_IA_revisadoANDREI.docx](DOCUMENTS/Articulo_Seguridad_Vivienda_IA_revisadoANDREI.docx)
- 📊 **Presentación:** [Google Slides](https://docs.google.com/presentation/d/16s7dWISyd8J5Wk_d9WWrWt844gS3caiZQgOhPyPJcPE/edit?usp=sharing)
- 🎥 **Video de demostración:** [DOCUMENTS/demo_sistema.mp4](DOCUMENTS/demo_sistema.mp4)
- 💻 **Código:** los archivos de este repositorio (instrucciones abajo).

---

El sistema combina:

- **Cámara + IA (Teachable Machine):** clasifica la entrada en Vacío, Andrei (dueño) o Externo.
- **Capa de verificación:** solo confirma una clase si la ve en 10 fotogramas seguidos con al menos 90 % de confianza.
- **Monitor de red WiFi:** avisa cuando un equipo se conecta o se desconecta de la red de la casa.
- **Telegram:** fotos, videos, alertas y control del sistema desde el celular.

Ante una persona externa, el bot envía una foto con los botones **Es conocido** y **Desconocido**.
Si se pulsa Desconocido, graba y envía un video de evidencia de 8 s.

Funciona en **Windows 10/11** y en **Linux (Ubuntu)**.

---

## Archivos

| Archivo | Qué es |
|---|---|
| `sistema_seguridad.py` | El sistema que queda corriendo en la casa (sin ventana). |
| `sistema_seguridad_demo.py` | El mismo sistema con un tablero en pantalla, para presentar. |
| `prueba_camara.py` | Prueba del modelo, la verificación y Telegram (datos del artículo). |
| `prueba_red.py` | Prueba del monitor de red (datos del artículo). |
| `config_ejemplo.py` | Plantilla de configuración, sin credenciales. |
| `keras_model.h5`, `labels.txt` | Modelo de Teachable Machine (MobileNetV2, clases Vacio / Andrei / Externo). |
| `requirements.txt` | Librerías necesarias. |
| `resultados/` | Datos crudos y resúmenes de las pruebas del 16-10-2026. |
| `DOCUMENTS/` | Artículo científico, video de demostración y link a la presentación. |

Todos los programas leen los mismos parámetros de `config.py`.

---

## 1. Requisitos

- Windows 10/11 o Linux (Ubuntu).
- Una webcam.
- Python 3.11 o 3.12 (TensorFlow todavía no funciona con 3.13 o superior).
- Una cuenta de Telegram.

Para comprobar tu versión de Python:

- Windows: `python --version`
- Linux: `python3 --version`

---

## 2. Instalar las librerías

Abre una terminal dentro de la carpeta del proyecto.

**Windows (PowerShell o la terminal de VS Code):**

    python -m venv venv
    venv\Scripts\activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt

**Linux:**

    sudo apt install -y python3-venv python3-pip
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt

Si alguna versión exacta de `requirements.txt` no existe para tu sistema, instala sin versiones (igual en Windows y Linux, con el `venv` activado):

    pip install tensorflow tf-keras opencv-python numpy requests pillow

Cada vez que abras una terminal nueva, activa el `venv` antes de correr el sistema:

- Windows: `venv\Scripts\activate`
- Linux: `source venv/bin/activate`

---

## 3. Crear el bot de Telegram

1. En Telegram busca **@BotFather**, manda `/newbot` y sigue los pasos: te da un **TOKEN**.
2. Abre tu bot y pulsa **Start** (si no, el bot no puede escribirte).
3. Busca **@userinfobot**, mándale `/start` y te da tu **CHAT_ID**.

---

## 4. Configurar

1. Copia `config_ejemplo.py` y nombra la copia `config.py`.
   - Windows: `copy config_ejemplo.py config.py`
   - Linux: `cp config_ejemplo.py config.py`
2. En `config.py` pon tu `TOKEN` y tu `CHAT_ID`.
3. En `REDES_CASA` pon los 3 primeros números de la IP de tu PC en la red de casa (ej. `192.168.0`).
   - Windows: mira tu IP con `ipconfig`.
   - Linux: mira tu IP con `ip addr`.
4. En `CONOCIDOS` pon la MAC de tu celular y tu nombre, para que el sistema te salude por nombre.

`config.py` está en `.gitignore`: nunca se sube a GitHub, así tus credenciales quedan solo en tu computadora.

Parámetros principales (ya vienen así en la plantilla):

| Parámetro | Valor | Qué hace |
|---|---|---|
| `UMBRAL_CONFIANZA` | 0.90 | Confianza mínima de cada fotograma. |
| `FRAMES_CONFIRMA` | 10 | Fotogramas seguidos para confirmar una clase. |
| `COOLDOWN_CAM_S` | 90 | Segundos mínimos entre alertas de cámara. |
| `SEGUNDOS_VIDEO_EVIDENCIA` | 8 | Duración del video de evidencia. |
| `INTERVALO_S` | 3 | Pausa entre barridos de la red. |
| `UMBRAL_AUSENCIA` | 3 | Barridos sin respuesta para dar un equipo por desconectado. |

---

## 5. Entrenar tu propio modelo (opcional)

El proyecto ya incluye `keras_model.h5` y `labels.txt`. Para entrenar el tuyo:

1. Entra a `https://teachablemachine.withgoogle.com` → **Standard image project**.
2. Crea 3 clases: **Vacio**, tu nombre y **Externo**.
3. Toma todas las fotos con la cámara en su posición final: el modelo también aprende el fondo y la luz.
4. **Train Model** → **Export Model** → **Tensorflow** → **Keras** → **Download**.
5. Copia `keras_model.h5` y `labels.txt` a la carpeta y pon los nombres de tus clases en `config.py`.

---

## 6. Correr

Con el `venv` activado:

**Sistema de la casa** (sin ventana; se detiene con `Ctrl+C`):

- Windows: `python sistema_seguridad.py`
- Linux: `python sistema_seguridad.py`

**Demo con tablero en pantalla** (para presentar; usa 20 s entre alertas para que el video no sea largo):

- Windows: `python sistema_seguridad_demo.py`
- Linux: `python sistema_seguridad_demo.py`

Teclas del demo: `q` salir · `a` armar/desarmar · `r` reiniciar · `f` pantalla completa.

No corras los dos a la vez: comparten el mismo bot de Telegram.

En VS Code también puedes elegir el intérprete del `venv` (`Ctrl+Shift+P` → **Python: Select Interpreter**) y usar el botón **▶**.

---

## 7. Comandos de Telegram

- `/foto` — foto en vivo de la entrada
- `/video` — video en vivo de 5 s
- `/estado` — equipos conectados a la red
- `/diario` — llegadas y salidas
- `/historial` — últimos 10 eventos
- `/resumen` · `/semana` — resumen del día o de 7 días
- `/exportar` — historial completo en CSV
- `/armar` · `/desarmar` — activar o apagar los avisos
- `/silencio 2h` — silenciar por un tiempo (30m, 2h)
- `/agregar MAC nombre` · `/quitar MAC` · `/conocidos` — equipos con nombre
- `/ayuda` — menú

El bot solo obedece al `CHAT_ID` configurado.

---

## 8. Solución de problemas

- **`No module named 'cv2'`** → no activaste el `venv` (paso 2).
- **`falta config.py`** → copia `config_ejemplo.py` como `config.py` y llénalo (paso 4).
- **No llega nada a Telegram** → revisa el TOKEN y el CHAT_ID, y que le diste **Start** al bot.
- **Error 409 de Telegram** → otro programa está usando el mismo bot. Ciérralo.
- **La cámara no abre** → cierra otras apps que usen la webcam (Teams, Zoom, OBS) o cambia `CAMARA` a 1 o 2.
  - Windows: para cerrar un `sistema_seguridad.py` que corre sin ventana, usa `Get-Process python` y `Stop-Process -Id <número>` en PowerShell.
  - Linux: usa `pkill -f sistema_seguridad.py`.
- **El monitor de red no avisa** → solo funciona en las redes listadas en `REDES_CASA`.
- **El modelo se equivoca mucho** → reentrena con fotos tomadas en el mismo lugar, posición y luz donde está la cámara.
- **Mensajes de `cuda` o `oneDNN` al iniciar** → son avisos de TensorFlow: no hay tarjeta gráfica NVIDIA y usa el procesador. No afectan.
