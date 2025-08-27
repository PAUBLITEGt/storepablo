import os
import json
import random
import string
import threading
import logging
from functools import wraps
from typing import Dict, Any, List, Optional
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# --- Configuración y Constantes ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN: Optional[str] = os.environ.get("TELEGRAM_TOKEN")
ADMIN: int = int(os.environ.get("ADMIN_ID", 7590578210))

if not TOKEN:
    logging.error("❌ La variable de entorno 'TELEGRAM_TOKEN' no está configurada.")
    exit()

BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
DB_USERS: str = os.path.join(BASE_DIR, "users.json")
DB_STOCK: str = os.path.join(BASE_DIR, "stock.json")
DB_KEYS: str = os.path.join(BASE_DIR, "claves.json")
DB_BANS: str = os.path.join(BASE_DIR, "ban_users.json")
DB_ADMINS: str = os.path.join(BASE_DIR, "admins.json")
DB_CARDS: str = os.path.join(BASE_DIR, "cards.json")
DB_CARD_KEYS: str = os.path.join(BASE_DIR, "card_keys.json")

# GIFs para el mensaje de inicio
START_MEDIA = [
    "https://64.media.tumblr.com/bff8a385b75b4f747ad5de78a917faae/99c3bba1a6801134-82/s540x810/7d5a2b6b57fb0ea5c61e41a935990618ec78669d.gif",
    "https://i.pinimg.com/originals/dc/d6/2f/dcd62f5fe32b1cabae1f89626c30fef6.gif",
    "https://i.pinimg.com/originals/cb/26/25/cb262560dbf553b91deeec5bd35d216b.gif",
    "https://giffiles.alphacoders.com/222/222779.gif",
    "https://giffiles.alphacoders.com/222/222779.gif",
    "https://i.pinimg.com/originals/dc/d6/2f/dcd62f5fe32b1cabae1f89626c30fef6.gif",
    "https://i.pinimg.com/originals/dc/d6/2f/dcd62f5fe32b1cabae1f89626c30fef6.gif",
]

# Estados para ConversationHandler
AWAITING_USER_ID_TO_REVOKE, AWAITING_STOCK_SITE, AWAITING_STOCK_MESSAGE, AWAITING_STOCK_ACCOUNTS, AWAITING_CARDS_SITE, AWAITING_CARDS_MESSAGE, AWAITING_CARDS_ACCOUNTS, AWAITING_ADMIN_ID, AWAITING_REMOVE_ADMIN_ID, BROADCAST_CONTENT, AWAITING_USER_ID_TO_BAN, AWAITING_USER_ID_TO_UNBAN = range(12)

# --- Funciones de Utilidad para Base de Datos ---
def load_data(path: str, default: Optional[Any] = None) -> Any:
    """
    Carga datos de un archivo JSON.
    Retorna el valor por defecto si el archivo no existe o hay un error.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.warning(f"Archivo no encontrado o con formato incorrecto: {path}")
        return default or {} if isinstance(default, dict) else default or []

def save_data(path: str, data: Any):
    """Guarda datos en un archivo JSON de forma segura."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    logging.info(f"Datos guardados en {path}")


# --- Decoradores para Verificación de Usuarios ---
def is_banned(user_id: int) -> bool:
    """Verifica si un usuario está baneado."""
    banned_users = load_data(DB_BANS, default=[])
    return user_id in banned_users

def is_admin(user_id: int) -> bool:
    """Verifica si un usuario tiene privilegios de administrador."""
    admins = load_data(DB_ADMINS, default=[])
    return user_id == ADMIN or user_id in admins

def check_ban(func):
    """Decorador para restringir el acceso a usuarios baneados."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return

        if user_id != ADMIN and is_banned(user_id):
            if update.effective_message:
                await update.effective_message.reply_text(
                    text="🚫 <b>Estás baneado y no puedes usar este bot.</b>",
                    parse_mode="HTML"
                )
            else:
                await update.callback_query.answer("🚫 Estás baneado y no puedes usar este bot.", show_alert=True)
            return
        return await func(update, ctx)
    return wrapper

def check_admin(func):
    """Decorador para restringir el acceso a usuarios admin y super admin."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return

        if not is_admin(user_id):
            if update.effective_message:
                await update.effective_message.reply_text("❌ No autorizado.")
            else:
                await update.callback_query.answer("❌ No autorizado.", show_alert=True)
            return
        return await func(update, ctx)
    return wrapper

def check_super_admin(func):
    """Decorador para restringir el acceso solo al creador del bot (ADMIN)."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return

        if user_id != ADMIN:
            if update.effective_message:
                await update.effective_message.reply_text("❌ No autorizado.")
            else:
                await update.callback_query.answer("❌ No autorizado.", show_alert=True)
            return
        return await func(update, ctx)
    return wrapper


# --- Teclados de Botones ---
def kb_start(uid: int) -> InlineKeyboardMarkup:
    """Genera el teclado de inicio, incluyendo el panel de admin si el usuario es el admin."""
    kb = [
        [
            InlineKeyboardButton("👤 Perfil", callback_data="profile"),
            InlineKeyboardButton("📦 Stock", callback_data="stock"),
            InlineKeyboardButton("📖 Comandos", callback_data="cmds"),
        ]
    ]
    if is_admin(uid):
        kb.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data="panel")])
    return InlineKeyboardMarkup(kb)

KB_ADMIN = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔐 Crear claves", callback_data="gen_cmd")],
    [InlineKeyboardButton("💎 SuperPro Key", callback_data="super_pro_key")],
    [InlineKeyboardButton("❌ Quitar plan premium", callback_data="revoke_premium_start")],
    [InlineKeyboardButton("👥 Ver usuarios", callback_data="users_cmd")],
    [InlineKeyboardButton("🚫 Banear usuario", callback_data="ban_user_start")],
    [InlineKeyboardButton("✅ Desbanear usuario", callback_data="unban_user_start")],
    [InlineKeyboardButton("➕ Subir Cuentas", callback_data="addstock_start")],
    [InlineKeyboardButton("➕ Subir Tarjetas", callback_data="addcards_start")],
    [InlineKeyboardButton("💳 Keys Tarjetas", callback_data="gen_cards_key")],
    [InlineKeyboardButton("📢 Enviar Anuncio", callback_data="send_msg_cmd")],
    [InlineKeyboardButton("👑 Promover Admin", callback_data="add_admin_start")],
    [InlineKeyboardButton("💀 Degradar Admin", callback_data="rem_admin_start")]
])

KB_STOCK_MENU = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("✅ Cuentas Premium", callback_data="show_stock_cuentas"),
        InlineKeyboardButton("💳 Tarjetas", callback_data="show_stock_tarjetas")
    ],
    [
        InlineKeyboardButton("⏪ Regresar", callback_data="start_menu")
    ]
])

KB_RETURN_TO_START = InlineKeyboardMarkup([
    [InlineKeyboardButton("⏪ Regresar", callback_data="start_menu")]
])


# --- Comandos de Inicio y Ayuda ---
@check_ban
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /start y notifica al admin sobre el nuevo usuario."""
    uid = update.effective_user.id
    user_info = update.effective_user

    users = load_data(DB_USERS, {})
    is_new_user = False
    if str(uid) not in users:
        users[str(uid)] = {
            "plan_normal": {"nombre": "Sin plan", "max": 0, "usados": 0},
            "plan_tarjetas": {"nombre": "Sin plan", "max": 0, "usados": 0},
            "invalid_key_attempts": 0
        }
        save_data(DB_USERS, users)
        is_new_user = False

    # Asegura que la estructura de datos esté completa para todos los usuarios
    user_data = users.get(str(uid), {})
    if "plan_normal" not in user_data:
        user_data["plan_normal"] = {"nombre": "Sin plan", "max": 0, "usados": 0}
    if "plan_tarjetas" not in user_data:
        user_data["plan_tarjetas"] = {"nombre": "Sin plan", "max": 0, "usados": 0}
    if "invalid_key_attempts" not in user_data:
        user_data["invalid_key_attempts"] = 0
    users[str(uid)] = user_data
    save_data(DB_USERS, users)


    if is_new_user and uid != ADMIN:
        try:
            admin_message = (
                f"🎉 <b>Nuevo usuario ha iniciado el bot:</b>\n"
                f"🆔 ID: <code>{user_info.id}</code>\n"
                f"👤 Nombre: <code>{user_info.first_name}</code>\n"
                f"🔗 Username: @{user_info.username or 'N/A'}"
            )
            await ctx.bot.send_message(chat_id=ADMIN, text=admin_message, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Error al enviar mensaje al admin: {e}")

    gif_url = random.choice(START_MEDIA)
    caption_text = (
        f"<u><b>🎉 Bienvenido a PAUBLITE_GT</b></u>\n\n"
        f"<b>🆔 Tu ID:</b> <code>{user_info.id}</code>\n"
        f"<b>👤 Tu Nombre:</b> <code>{user_info.first_name}</code>\n"
        f"<b>🔗 Tu Username:</b> @{user_info.username or 'N/A'}\n\n"
        f"<b>💳 Compra claves premium aquí 👉 @PAUBLITE_GT @deluxeGt @NigerianStore</b>\n"
        f"<b>🔗 Canal Oficial:</b> https://t.me/+kpO7XeoQsDQ0MWM0\n\n"
        f"<b>📌 Comandos:</b>\n"
        f"  - <code>/key CLAVE</code>\n"
        f"  - <code>/get sitio cant</code>\n\n"
        f"<b>📌 Administración:</b> Panel abajo"
    )

    try:
        await ctx.bot.send_animation(
            chat_id=update.effective_chat.id,
            animation=gif_url,
            caption=caption_text,
            parse_mode="HTML",
            reply_markup=kb_start(uid)
        )
    except error.BadRequest as e:
        logging.error(f"Error al enviar animación: {e}. Intentando enviar como foto...")
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption_text,
            parse_mode="HTML",
            reply_markup=kb_start(uid)
        )

# --- Comandos de Usuario ---
@check_ban
async def key_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /key para activar una clave."""
    if not ctx.args:
        await update.effective_chat.send_message(
            text="🤖 <b>Uso:</b>\n<code>/key CLAVE</code>\n\n💎 Compra claves premium\n👉 @PAUBLITE_GT\n",
            parse_mode="HTML"
        )
        return

    clave = ctx.args[0].strip()
    claves = load_data(DB_KEYS, {})
    card_keys = load_data(DB_CARD_KEYS, {})
    uid = str(update.effective_user.id)
    users = load_data(DB_USERS, {})
    banned_users = load_data(DB_BANS, default=[])

    # Asegura que la estructura de datos del usuario esté completa
    user_data = users.get(uid)
    if not user_data:
        user_data = {
            "plan_normal": {"nombre": "Sin plan", "max": 0, "usados": 0},
            "plan_tarjetas": {"nombre": "Sin plan", "max": 0, "usados": 0},
            "invalid_key_attempts": 0
        }
        users[uid] = user_data
    else:
        if "plan_normal" not in user_data:
            user_data["plan_normal"] = {"nombre": "Sin plan", "max": 0, "usados": 0}
        if "plan_tarjetas" not in user_data:
            user_data["plan_tarjetas"] = {"nombre": "Sin plan", "max": 0, "usados": 0}
        if "invalid_key_attempts" not in user_data:
            user_data["invalid_key_attempts"] = 0

    save_data(DB_USERS, users) # Guarda la estructura de datos actualizada

    is_card_key = clave in card_keys
    is_normal_key = clave in claves

    if is_normal_key:
        # Lógica para canjear clave normal
        if user_data.get("plan_normal", {}).get("nombre") != "Sin plan" and user_data.get("plan_normal", {}).get("max", 0) > user_data.get("plan_normal", {}).get("usados", 0):
            await update.effective_chat.send_message(
                text="❌ <b>Ya tienes un plan de cuentas activo.</b>\nNo puedes activar otra clave hasta que termines tus usos actuales.",
                parse_mode="HTML"
            )
            return

        plan, maxi = claves.pop(clave)
        save_data(DB_KEYS, claves)
        user_data["plan_normal"]["nombre"] = plan
        user_data["plan_normal"]["max"] = maxi
        user_data["plan_normal"]["usados"] = 0
        save_data(DB_USERS, users)

        await update.effective_chat.send_message(
            text=(
                f"✨ <b>¡Felicidades!</b> 🎉\n"
                f"Has activado una nueva clave premium. Se ha activado el plan <b>{plan}</b> con <b>{maxi}</b> usos."
            ),
            parse_mode="HTML"
        )
        return

    elif is_card_key:
        # Lógica para canjear clave de tarjetas
        if user_data.get("plan_tarjetas", {}).get("nombre") != "Sin plan" and user_data.get("plan_tarjetas", {}).get("max", 0) > user_data.get("plan_tarjetas", {}).get("usados", 0):
            await update.effective_chat.send_message(
                text="❌ <b>Ya tienes un plan de tarjetas activo.</b>\nNo puedes activar otra clave hasta que termines tus usos actuales.",
                parse_mode="HTML"
            )
            return

        plan, maxi = card_keys.pop(clave)
        save_data(DB_CARD_KEYS, card_keys)
        user_data["plan_tarjetas"]["nombre"] = plan
        user_data["plan_tarjetas"]["max"] = maxi
        user_data["plan_tarjetas"]["usados"] = 0
        save_data(DB_USERS, users)

        await update.effective_chat.send_message(
            text=(
                f"✨ <b>¡Felicidades!</b> 🎉\n"
                f"Has activado un nuevo plan para acceder a tarjetas. Se ha activado el plan <b>{plan}</b> con <b>{maxi}</b> usos."
            ),
            parse_mode="HTML"
        )
        return

    else:
        # Lógica para clave inválida
        user_data["invalid_key_attempts"] = user_data.get("invalid_key_attempts", 0) + 1
        save_data(DB_USERS, users)

        if user_data["invalid_key_attempts"] >= 3:
            if int(uid) not in banned_users:
                banned_users.append(int(uid))
                save_data(DB_BANS, banned_users)

            await update.effective_chat.send_message(
                text="🚫 <b>¡Has sido baneado!</b> Demasiados intentos fallidos con claves inválidas. No puedes usar más este bot.",
                parse_mode="HTML"
            )
            return

        await update.effective_chat.send_message(
            text=(
                f"❌ <b>Clave inválida. No insistas o serás baneado.</b>\n"
                f"Intentos restantes: {3 - user_data['invalid_key_attempts']}\n\n"
                "<b>💳 Compra claves premium</b> con un mensaje a:\n"
                "🔗 @PAUBLITE_GT\n"
            ),
            parse_mode="HTML"
        )
        return

@check_ban
async def get_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /get para obtener cuentas."""
    if len(ctx.args) < 2:
        await update.effective_chat.send_message(text="Uso: /get sitio cantidad")
        return

    sitio = ctx.args[0].strip().lower()
    try:
        cant = int(ctx.args[1])
    except ValueError:
        await update.effective_chat.send_message(text="Cantidad debe ser un número.")
        return

    uid = str(update.effective_user.id)
    users = load_data(DB_USERS, {})
    user_data = users.get(uid)

    if not user_data or (user_data.get("plan_normal", {}).get("nombre") == "Sin plan" and user_data.get("plan_tarjetas", {}).get("nombre") == "Sin plan"):
        await update.effective_chat.send_message(text="❌ Sin plan activo.")
        return

    # --- LÓGICA PARA BUSCAR STOCK DE CUENTAS ---
    stock = load_data(DB_STOCK, {})
    cuentas_disponibles = None

    # Busca la clave de forma insensible a mayúsculas y minúsculas
    for key in stock.keys():
        if key.lower() == sitio:
            cuentas_disponibles = stock.get(key)
            sitio = key  # Usa la clave original para mostrar el nombre
            break

    # Si se encontró el stock de cuentas
    if cuentas_disponibles:
        plan_normal = user_data.get("plan_normal", {})
        if plan_normal.get("nombre") == "Sin plan":
            await update.effective_chat.send_message(
                text="❌ Necesitas una clave premium normal para acceder a este stock."
            )
            return

        disp = plan_normal.get("max", 0) - plan_normal.get("usados", 0)
        if cant > disp:
            await update.effective_chat.send_message(text=f"❌ Te quedan {disp} accesos.")
            return

        # Verifica si el stock está en el nuevo formato (diccionario)
        if isinstance(cuentas_disponibles, dict) and "accounts" in cuentas_disponibles:
            accounts_list = cuentas_disponibles.get("accounts", [])
            usage_message = cuentas_disponibles.get("message", "")

            if not accounts_list or len(accounts_list) < cant:
                await update.effective_chat.send_message(text=f"❌ Sin stock suficiente para {sitio}.")
                return

            cuentas_a_enviar = accounts_list[:cant]
            stock[sitio]["accounts"] = accounts_list[cant:] # Obtenemos el resto de las cuentas

            if not cuentas_a_enviar:
                await update.effective_chat.send_message(text=f"❌ Sin stock suficiente para {sitio}.")
                return

            plan_normal["usados"] = plan_normal.get("usados", 0) + cant
            save_data(DB_STOCK, stock)
            save_data(DB_USERS, users)

            for cuenta_data in cuentas_a_enviar:
                account_info = cuenta_data.get("account", "N/A")
                file_id = cuenta_data.get("file_id")
                file_type = cuenta_data.get("file_type")

                final_text = (
                    f"🎁 <b>{sitio.upper()}</b>\n\n"
                    f"✨ Cuenta: <code>{account_info}</code>\n"
                    f"<i>{usage_message}</i>\n\n"
                    f"Usos: {plan_normal['usados']}/{plan_normal['max']}"
                )

                if file_id and file_type:
                    try:
                        if file_type == 'photo':
                            await ctx.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=file_id,
                                caption=final_text,
                                parse_mode="HTML"
                            )
                        elif file_type == 'video':
                            await ctx.bot.send_video(
                                chat_id=update.effective_chat.id,
                                video=file_id,
                                caption=final_text,
                                parse_mode="HTML"
                            )
                        elif file_type == 'animation':
                            await ctx.bot.send_animation(
                                chat_id=update.effective_chat.id,
                                animation=file_id,
                                caption=final_text,
                                parse_mode="HTML"
                            )
                    except Exception as e:
                        logging.error(f"Error al enviar el archivo {file_type}: {e}. Enviando como texto...")
                        await update.effective_chat.send_message(text=final_text, parse_mode="HTML")
                else:
                    await update.effective_chat.send_message(text=final_text, parse_mode="HTML")
        else: # Formato de lista de texto antiguo
            if not cuentas_disponibles or len(cuentas_disponibles) < cant:
                await update.effective_chat.send_message(text=f"❌ Sin stock suficiente para {sitio}.")
                return

            cuentas = cuentas_disponibles[:cant]
            stock[sitio] = cuentas_disponibles[cant:]
            plan_normal["usados"] = plan_normal.get("usados", 0) + cant
            save_data(DB_STOCK, stock)
            save_data(DB_USERS, users)

            texto = "\n".join([f"✨ <code>{c}</code>" for c in cuentas])
            await update.effective_chat.send_message(
                text=f"🎁 <b>{sitio.upper()}</b> ×{cant}\n\n{texto}\n\nUsos: {plan_normal['usados']}/{plan_normal['max']}",
                parse_mode="HTML"
            )
        return

    # --- Lógica para obtener stock de TARJETAS ---
    cards = load_data(DB_CARDS, {})
    tarjetas_disponibles = None

    # Busca la clave de forma insensible a mayúsculas y minúsculas
    for key in cards.keys():
        if key.lower() == sitio:
            tarjetas_disponibles = cards.get(key)
            sitio = key  # Usa la clave original para mostrar el nombre
            break

    if tarjetas_disponibles:
        plan_tarjetas = user_data.get("plan_tarjetas", {})
        if plan_tarjetas.get("nombre") == "Sin plan":
            await update.effective_chat.send_message(
                text="❌ Necesitas una clave de tarjetas para acceder a este stock."
            )
            return

        disp = plan_tarjetas.get("max", 0) - plan_tarjetas.get("usados", 0)
        if cant > disp:
            await update.effective_chat.send_message(text=f"❌ Te quedan {disp} accesos para tarjetas.")
            return

        # Verifica si el stock de tarjetas está en el nuevo formato (diccionario)
        if isinstance(tarjetas_disponibles, dict) and "cards" in tarjetas_disponibles:
            card_list = tarjetas_disponibles.get("cards", [])
            usage_message = tarjetas_disponibles.get("message", "")

            if not card_list or len(card_list) < cant:
                await update.effective_chat.send_message(text=f"❌ Sin stock de tarjetas suficiente para {sitio}.")
                return

            tarjetas_a_enviar = card_list[:cant]
            cards[sitio]["cards"] = card_list[cant:]

            plan_tarjetas["usados"] = plan_tarjetas.get("usados", 0) + cant
            save_data(DB_CARDS, cards)
            save_data(DB_USERS, users)

            for tarjeta_data in tarjetas_a_enviar:
                card_info = tarjeta_data.get("card", "N/A")
                file_id = tarjeta_data.get("file_id")
                file_type = tarjeta_data.get("file_type")

                final_text = (
                    f"🎁 <b>{sitio.upper()}</b>\n\n"
                    f"💳 Tarjeta: <code>{card_info}</code>\n"
                    f"<i>{usage_message}</i>\n\n"
                    f"Usos: {plan_tarjetas['usados']}/{plan_tarjetas['max']}"
                )

                if file_id and file_type:
                    try:
                        if file_type == 'photo':
                            await ctx.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=file_id,
                                caption=final_text,
                                parse_mode="HTML"
                            )
                        elif file_type == 'video':
                            await ctx.bot.send_video(
                                chat_id=update.effective_chat.id,
                                video=file_id,
                                caption=final_text,
                                parse_mode="HTML"
                            )
                        elif file_type == 'animation':
                            await ctx.bot.send_animation(
                                chat_id=update.effective_chat.id,
                                animation=file_id,
                                caption=final_text,
                                parse_mode="HTML"
                            )
                    except Exception as e:
                        logging.error(f"Error al enviar el archivo {file_type}: {e}. Enviando como texto...")
                        await update.effective_chat.send_message(text=final_text, parse_mode="HTML")
                else:
                    await update.effective_chat.send_message(text=final_text, parse_mode="HTML")

        else: # Formato de lista de texto antiguo
            if not tarjetas_disponibles or len(tarjetas_disponibles) < cant:
                await update.effective_chat.send_message(text=f"❌ Sin stock de tarjetas suficiente para {sitio}.")
                return

            tarjetas = tarjetas_disponibles[:cant]
            cards[sitio] = tarjetas_disponibles[cant:]
            plan_tarjetas["usados"] = plan_tarjetas.get("usados", 0) + cant
            save_data(DB_CARDS, cards)
            save_data(DB_USERS, users)

            texto = "\n".join([f"💳 <code>{t}</code>" for t in tarjetas])
            await update.effective_chat.send_message(
                text=f"🎁 <b>{sitio.upper()}</b> ×{cant}\n\n{texto}\n\nUsos: {plan_tarjetas['usados']}/{plan_tarjetas['max']}",
                parse_mode="HTML"
            )
        return

    await update.effective_chat.send_message(text=f"❌ Sin stock suficiente para <b>{sitio}</b>.", parse_mode="HTML")

# --- Manejador genérico para mensajes no reconocidos ---
async def handle_unknown_messages(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Responde a mensajes que no son comandos."""
    await update.message.reply_text(
        "❌ Lo siento, no entiendo ese comando. Usa <code>/start</code> para ver el menú principal.\n\n"
        "<b>💳 Compra acceso premium aquí</b> 👉 @PAUBLITE_GT",
        parse_mode="HTML"
    )

# --- Funciones de Callback para Botones ---
async def return_to_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Regresa al menú de inicio."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    gif_url = random.choice(START_MEDIA)
    caption_text = (
        f"<u><b>🎉 Bienvenido de nuevo a PAUBLITE_GT</b></u>\n\n"
        f"<b>ID:</b> <code>{uid}</code>\n"
        f"<b>Compra claves premium aquí 👉 @PAUBLITE_GT @deluxeGt @NigerianStore</b>\n"
        f"<b>Canal Oficial:</b> https://t.me/+kpO7XeoQsDQ0MWM0\n\n"
    )

    await query.edit_message_caption(
        caption=caption_text,
        parse_mode="HTML",
        reply_markup=kb_start(uid)
    )

async def show_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra el perfil del usuario."""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    users = load_data(DB_USERS, {})
    user_data = users.get(user_id)

    if not user_data:
        await query.edit_message_caption(
            caption="❌ No se encontró tu perfil. Intenta reiniciar con /start.",
            reply_markup=KB_RETURN_TO_START
        )
        return

    plan_normal = user_data.get('plan_normal', {"nombre": "Sin plan", "usados": 0, "max": 0})
    plan_tarjetas = user_data.get('plan_tarjetas', {"nombre": "Sin plan", "usados": 0, "max": 0})

    profile_text = (
        f"<u><b>👤 PERFIL DE USUARIO</b></u>\n\n"
        f"<b>🆔 ID:</b> <code>{user_id}</code>\n"
        f"<b>👤 Nombre:</b> <code>{query.from_user.full_name}</code>\n"
        f"<b>🔗 Username:</b> @{query.from_user.username or 'N/A'}\n"
        f"<b>Plan Cuentas:</b> <i>{plan_normal['nombre']}</i>\n"
        f"<b>Usos:</b> {plan_normal['usados']}/{plan_normal['max']}\n"
        f"<b>Plan Tarjetas:</b> <i>{plan_tarjetas['nombre']}</i>\n"
        f"<b>Usos:</b> {plan_tarjetas['usados']}/{plan_tarjetas['max']}\n"
    )

    await query.edit_message_caption(
        caption=profile_text,
        parse_mode="HTML",
        reply_markup=KB_RETURN_TO_START
    )

async def show_cmds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra la lista de comandos."""
    query = update.callback_query
    await query.answer()

    text = (
        f"<u><b>📖 COMANDOS DISPONIBLES</b></u>\n\n"
        f"<b>• /start</b> - Inicia el bot y muestra el menú principal.\n"
        f"<b>• /key &lt;clave&gt;</b> - Activa una clave premium para obtener usos.\n"
        f"<b>• /get &lt;sitio&gt; &lt;cantidad&gt;</b> - Obtiene cuentas del stock. Ej: <code>/get netflix 1</code>\n"
    )

    await query.edit_message_caption(
        caption=text,
        parse_mode="HTML",
        reply_markup=KB_RETURN_TO_START
    )

async def show_admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra el panel de administración."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_caption(
        caption="<u><b>⚙️ PANEL DE ADMINISTRACIÓN</b></u>\n\n"
                "Selecciona una opción para gestionar el bot.",
        parse_mode="HTML",
        reply_markup=KB_ADMIN
    )

# --- Lógica de Stock Separada ---
async def show_stock_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra el menú para elegir entre stock de cuentas o tarjetas."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_caption(
        caption="<u><b>📦 Selecciona el tipo de stock que deseas ver:</b></u>",
        parse_mode="HTML",
        reply_markup=KB_STOCK_MENU
    )

async def show_cuentas_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra el stock de cuentas premium."""
    query = update.callback_query
    await query.answer()

    stock = load_data(DB_STOCK, {})
    message = "<u><b>✅ STOCK DE CUENTAS DISPONIBLES</b></u>\n\n"

    if not stock:
        message += "❌ No hay stock disponible de cuentas en este momento."
    else:
        for site, data in stock.items():
            if isinstance(data, list):
                count = len(data)
            else:
                count = len(data.get("accounts", []))
            message += f"<b>{site.upper()}</b> → <b>{count}</b> cuentas\n"

    await query.edit_message_caption(
        caption=message,
        parse_mode="HTML",
        reply_markup=KB_RETURN_TO_START
    )

async def show_cards_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra el stock de tarjetas."""
    query = update.callback_query
    await query.answer()

    cards = load_data(DB_CARDS, {})
    message = "<u><b>💳 STOCK DE TARJETAS DISPONIBLES</b></u>\n\n"

    if not cards:
        message += "❌ No hay stock disponible de tarjetas en este momento."
    else:
        for bank, data in cards.items():
            if isinstance(data, list):
                count = len(data)
            else:
                count = len(data.get("cards", []))
            message += f"<b>{bank.upper()}</b> → <b>{count}</b> tarjetas\n"

    await query.edit_message_caption(
        caption=message,
        parse_mode="HTML",
        reply_markup=KB_RETURN_TO_START
    )

# --- Comandos de Admin ---
@check_admin
async def gen_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /gen para generar claves de activación con un formato específico."""
    claves = load_data(DB_KEYS, {})
    planes = [
        (1, "Bronce 1"),
        (2, "Plata 2"),
        (3, "Oro 3"),
        (4, "Diamante 4")
    ]
    mensaje_salida = "✨ <b>Claves Premium Generadas:</b>\n\n"

    for usos, nombre in planes:
        codigo_unico = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        key = f"paublte-gen{usos}-{codigo_unico}"

        claves[key] = (nombre, usos)
        mensaje_salida += f"• <code>{key}</code> → <b>{nombre}</b>\n"

    save_data(DB_KEYS, claves)
    await update.effective_chat.send_message(text=mensaje_salida, parse_mode="HTML")

@check_admin
async def super_pro_key_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Genera una clave 'SuperPro' con 1000 usos."""
    claves = load_data(DB_KEYS, {})
    codigo_unico = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    key = f"paublte-superpro-{codigo_unico}"

    plan_name = "SuperPro"
    max_uses = 1000

    claves[key] = (plan_name, max_uses)
    save_data(DB_KEYS, claves)

    await update.effective_chat.send_message(
        text=f"✨ <b>Clave SuperPro Generada:</b>\n\n"
             f"<code>{key}</code> → <b>{plan_name}</b>\n"
             f"Accesos: <b>{max_uses}</b>",
        parse_mode="HTML"
    )

@check_admin
async def gen_cards_key_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando para generar una clave para el stock de tarjetas."""
    card_keys = load_data(DB_CARD_KEYS, {})
    codigo_unico = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    key = f"paublte-tarjeta-{codigo_unico}"

    plan_name = "Plan Tarjetas"
    max_uses = 1

    card_keys[key] = (plan_name, max_uses)
    save_data(DB_CARD_KEYS, card_keys)

    await update.effective_chat.send_message(
        text=f"✨ <b>Clave para Tarjetas Generada:</b>\n\n"
             f"<code>{key}</code> → <b>{plan_name}</b>\n"
             f"Accesos: <b>{max_uses}</b>",
        parse_mode="HTML"
    )

@check_admin
async def users_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra la lista de usuarios y sus planes."""
    users = load_data(DB_USERS, {})
    banned_users = load_data(DB_BANS, default=[])
    lines = []

    await update.effective_chat.send_message("🔍 <b>Obteniendo información de usuarios...</b>", parse_mode="HTML")

    for uid, data in users.items():
        try:
            user_info = await ctx.bot.get_chat(int(uid))
            username = f"@{user_info.username}" if user_info.username else "N/A"
            full_name = user_info.full_name
            status = "baneado 🚫" if int(uid) in banned_users else "activo ✅"

            plan_normal_info = "Sin plan (0/0)"
            plan_tarjetas_info = "Sin plan (0/0)"

            if 'plan_normal' in data:
                plan_normal_info = f"{data['plan_normal']['nombre']} ({data['plan_normal']['usados']}/{data['plan_normal']['max']})"
            elif 'plan' in data: # Compatibilidad con formato antiguo
                plan_normal_info = f"{data['plan']} ({data['usados']}/{data['max']})"

            if 'plan_tarjetas' in data:
                plan_tarjetas_info = f"{data['plan_tarjetas']['nombre']} ({data['plan_tarjetas']['usados']}/{data['plan_tarjetas']['max']})"

            lines.append(
                f"• ID: <code>{uid}</code>\n"
                f"  Nombre: <code>{full_name}</code>\n"
                f"  Username: <code>{username}</code>\n"
                f"  Plan Normal: {plan_normal_info}\n"
                f"  Plan Tarjetas: {plan_tarjetas_info}\n"
                f"  Estado: {status}"
            )
        except error.TelegramError as e:
            logging.warning(f"No se pudo obtener la información para el usuario con ID {uid}: {e}")
            plan_normal_info = "Sin plan"
            plan_tarjetas_info = "Sin plan"
            if 'plan_normal' in data:
                plan_normal_info = f"{data['plan_normal']['nombre']} ({data['plan_normal']['usados']}/{data['plan_normal']['max']})"
            if 'plan_tarjetas' in data:
                plan_tarjetas_info = f"{data['plan_tarjetas']['nombre']} ({data['plan_tarjetas']['usados']}/{data['plan_tarjetas']['max']})"

            lines.append(f"• ID: <code>{uid}</code>\n"
                         f"  Nombre: <code>(No disponible)</code>\n"
                         f"  Plan Normal: {plan_normal_info}\n"
                         f"  Plan Tarjetas: {plan_tarjetas_info}\n"
                         f"  Estado: {'baneado 🚫' if int(uid) in banned_users else 'activo ✅'}")
        except Exception as e:
            logging.error(f"Error inesperado al procesar usuario {uid}: {e}")
            plan_normal_info = "Sin plan"
            plan_tarjetas_info = "Sin plan"
            if 'plan_normal' in data:
                plan_normal_info = f"{data['plan_normal']['nombre']} ({data['plan_normal']['usados']}/{data['plan_normal']['max']})"
            if 'plan_tarjetas' in data:
                plan_tarjetas_info = f"{data['plan_tarjetas']['nombre']} ({data['plan_tarjetas']['usados']}/{data['plan_tarjetas']['max']})"

            lines.append(f"• ID: <code>{uid}</code>\n"
                         f"  Nombre: <code>(Error)</code>\n"
                         f"  Plan Normal: {plan_normal_info}\n"
                         f"  Plan Tarjetas: {plan_tarjetas_info}\n"
                         f"  Estado: {'baneado 🚫' if int(uid) in banned_users else 'activo ✅'}")

    chunk_size = 10
    chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]

    if not chunks:
        await update.effective_chat.send_message(
            text="📭 No hay usuarios registrados.",
            parse_mode="HTML"
        )
        return

    await update.effective_chat.send_message("👥 <b>Usuarios Registrados:</b>\n\n", parse_mode="HTML")
    for chunk in chunks:
        await update.effective_chat.send_message(
            text="\n\n".join(chunk),
            parse_mode="HTML"
        )

# --- Funciones de Anuncio ---
@check_admin
async def start_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inicia el flujo de conversación para enviar un mensaje a todos los usuarios."""
    await update.effective_chat.send_message(
        "Por favor, envía el mensaje que quieres enviar a todos los usuarios (texto, imagen, video o gif)."
    )
    return BROADCAST_CONTENT

async def receive_broadcast_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Recibe el contenido y lo envía a todos los usuarios."""
    users = load_data(DB_USERS, {})
    total_users = len(users)
    total_sent = 0
    total_failed = 0

    await update.message.reply_text(f"🚀 <b>Iniciando envío a {total_users} usuarios...</b>", parse_mode="HTML")

    msg_type = 'text'
    msg_content = ""
    msg_caption = ""

    if update.message.photo:
        msg_type = 'photo'
        msg_content = update.message.photo[-1].file_id
        msg_caption = update.message.caption or ""
    elif update.message.video:
        msg_type = 'video'
        msg_content = update.message.video.file_id
        msg_caption = update.message.caption or ""
    elif update.message.animation:
        msg_type = 'animation'
        msg_content = update.message.animation.file_id
        msg_caption = update.message.caption or ""
    elif update.message.text:
        msg_type = 'text'
        msg_content = update.message.text
    else:
        await update.message.reply_text("❌ Formato no soportado. Por favor, envía texto, una imagen, un video o un gif.")
        return BROADCAST_CONTENT

    for uid in users.keys():
        try:
            if msg_type == 'text':
                await ctx.bot.send_message(chat_id=int(uid), text=msg_content, parse_mode="HTML")
            elif msg_type == 'photo':
                await ctx.bot.send_photo(chat_id=int(uid), photo=msg_content, caption=msg_caption, parse_mode="HTML")
            elif msg_type == 'video':
                await ctx.bot.send_video(chat_id=int(uid), video=msg_content, caption=msg_caption, parse_mode="HTML")
            elif msg_type == 'animation':
                await ctx.bot.send_animation(chat_id=int(uid), animation=msg_content, caption=msg_caption, parse_mode="HTML")
            total_sent += 1
        except Exception as e:
            total_failed += 1
            logging.error(f"Error al enviar mensaje a {uid}: {e}")

    await update.message.reply_text(
        f"✅ <b>Envío completado.</b>\n"
        f"Mensajes enviados: {total_sent}\n"
        f"Mensajes fallidos: {total_failed}",
        parse_mode="HTML"
    )

    return ConversationHandler.END

async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END


# --- Lógica de Administración (Subir stock, ban, etc.) ---
@check_admin
async def revoke_premium_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inicia el proceso para quitar un plan premium a un usuario."""
    await update.effective_chat.send_message("Por favor, envía el ID del usuario al que quieres quitarle el plan premium.")
    return AWAITING_USER_ID_TO_REVOKE

@check_admin
async def revoke_premium_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Recibe el ID del usuario y le quita el plan premium."""
    try:
        user_id_to_revoke = str(int(update.message.text))
    except (ValueError, IndexError):
        await update.message.reply_text("❌ El ID del usuario debe ser un número. Intenta de nuevo o envía /cancel.")
        return AWAITING_ID_TO_REVOKE

    users = load_data(DB_USERS, {})

    if user_id_to_revoke not in users:
        await update.message.reply_text("❌ Usuario no encontrado. Verifica el ID.")
    else:
        user_data = users[user_id_to_revoke]
        user_data["plan_normal"] = {"nombre": "Sin plan", "max": 0, "usados": 0}
        user_data["plan_tarjetas"] = {"nombre": "Sin plan", "max": 0, "usados": 0}
        save_data(DB_USERS, users)

        await update.message.reply_text(f"✅ Se ha quitado el plan premium al usuario con ID <code>{user_id_to_revoke}</code>.", parse_mode="HTML")

        # Notificar al usuario afectado
        try:
            await ctx.bot.send_message(
                chat_id=int(user_id_to_revoke),
                text="❌ Tu plan premium ha sido eliminado por un administrador."
            )
        except Exception as e:
            logging.error(f"No se pudo notificar al usuario {user_id_to_revoke}: {e}")

    return ConversationHandler.END


@check_admin
async def ban_user_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("Por favor, envía el ID del usuario que quieres banear.")
    return AWAITING_USER_ID_TO_BAN

@check_admin
async def ban_user_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        user_id_to_ban = int(update.message.text)
    except (ValueError, IndexError):
        await update.message.reply_text("❌ El ID del usuario debe ser un número. Intenta de nuevo o envía /cancel.")
        return AWAITING_USER_ID_TO_BAN

    banned_users = load_data(DB_BANS, default=[])
    if user_id_to_ban in banned_users:
        await update.message.reply_text("❌ Este usuario ya está baneado.")
    else:
        banned_users.append(user_id_to_ban)
        save_data(DB_BANS, banned_users)
        await update.message.reply_text(f"✅ Usuario con ID <code>{user_id_to_ban}</code> baneado con éxito.", parse_mode="HTML")

    return ConversationHandler.END

@check_admin
async def unban_user_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("Por favor, envía el ID del usuario que quieres desbanear.")
    return AWAITING_USER_ID_TO_UNBAN

@check_admin
async def unban_user_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        user_id_to_unban = int(update.message.text)
    except (ValueError, IndexError):
        await update.message.reply_text("❌ El ID del usuario debe ser un número. Intenta de nuevo o envía /cancel.")
        return AWAITING_USER_ID_TO_UNBAN

    banned_users = load_data(DB_BANS, default=[])
    if user_id_to_unban not in banned_users:
        await update.message.reply_text("❌ Este usuario no está baneado.")
    else:
        banned_users.remove(user_id_to_unban)
        save_data(DB_BANS, banned_users)

        users = load_data(DB_USERS, {})
        user_id_str = str(user_id_to_unban)
        if user_id_str in users:
            users[user_id_str]['invalid_key_attempts'] = 0
            save_data(DB_USERS, users)

        await update.message.reply_text(f"✅ Usuario con ID <code>{user_id_to_unban}</code> desbaneado con éxito. Sus intentos de clave han sido reiniciados.", parse_mode="HTML")

    return ConversationHandler.END


# --- NUEVAS FUNCIONES PARA SUBIR STOCK (CUENTAS Y TARJETAS) ---
async def start_add_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.message.reply_text("<b>Paso 1:</b> Por favor, envía el nombre del sitio (ej: Netflix, Spotify).", parse_mode="HTML")
    return AWAITING_STOCK_SITE

async def get_stock_site(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["stock_site"] = update.message.text.strip().lower()
    await update.message.reply_text("<b>Paso 2:</b> Ahora, envía el mensaje de uso que quieres agregar a todas las cuentas de este stock. Si no quieres mensaje, escribe 'N/A'.", parse_mode="HTML")
    return AWAITING_STOCK_MESSAGE

async def get_stock_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["stock_message"] = update.message.text.strip()
    ctx.user_data["temp_accounts"] = []
    await update.message.reply_text(
        "<b>Paso 3:</b> Ahora, envía las cuentas. Puedes:\n\n"
        "1. Enviar una <b>foto, video o GIF</b> con los datos de la cuenta en el pie de foto.\n"
        "2. Enviar un <b>mensaje de texto</b> con las cuentas separadas por líneas.\n\n"
        "Cuando termines, envía el comando <code>/done</code>",
        parse_mode="HTML"
    )
    return AWAITING_STOCK_ACCOUNTS

async def receive_accounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    caption = update.message.caption or update.message.text
    file_id = None
    file_type = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = 'photo'
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = 'video'
    elif update.message.animation:
        file_id = update.message.animation.file_id
        file_type = 'animation'
    elif update.message.text:
        file_id = None
        file_type = 'text'

    if not caption:
        await update.message.reply_text("❌ Por favor, envía los datos de la cuenta en el pie de foto del archivo multimedia o en el mensaje de texto.")
        return AWAITING_STOCK_ACCOUNTS

    if file_type == 'text':
        accounts = [acc.strip() for acc in caption.split('\n') if acc.strip()]
        if not accounts:
            await update.message.reply_text("❌ Por favor, envía al menos una cuenta (una por línea).")
            return AWAITING_STOCK_ACCOUNTS
        for acc in accounts:
            ctx.user_data["temp_accounts"].append({"account": acc, "file_id": None, "file_type": "text"})
        await update.message.reply_text(f"✅ Se agregaron {len(accounts)} cuentas. Envía más o usa /done para finalizar.")
    else:
        ctx.user_data["temp_accounts"].append({"account": caption.strip(), "file_id": file_id, "file_type": file_type})
        await update.message.reply_text(f"✅ Cuenta con {file_type} agregada. Envía otra o usa /done para finalizar.")

    return AWAITING_STOCK_ACCOUNTS

async def finish_add_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    site = ctx.user_data.get("stock_site")
    message = ctx.user_data.get("stock_message")
    accounts_to_add = ctx.user_data.get("temp_accounts", [])

    if not accounts_to_add:
        await update.message.reply_text("❌ No agregaste ninguna cuenta. Operación cancelada.")
        return ConversationHandler.END

    stock = load_data(DB_STOCK, {})
    stock[site] = {"message": message, "accounts": accounts_to_add}
    save_data(DB_STOCK, stock)

    await update.message.reply_text(f"✅ Se han subido <b>{len(accounts_to_add)}</b> cuentas para <code>{site}</code> con éxito.", parse_mode="HTML")
    return ConversationHandler.END


# --- NUEVAS FUNCIONES PARA SUBIR STOCK (TARJETAS) ---
async def start_add_cards(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.message.reply_text("<b>Paso 1:</b> Por favor, envía el nombre del banco (ej: Turquia, España).", parse_mode="HTML")
    return AWAITING_CARDS_SITE

async def get_cards_site(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["cards_site"] = update.message.text.strip().lower()
    await update.message.reply_text("<b>Paso 2:</b> Ahora, envía el mensaje de uso que quieres agregar a todas las tarjetas de este stock. Si no quieres mensaje, escribe 'N/A'.", parse_mode="HTML")
    return AWAITING_CARDS_MESSAGE

async def get_cards_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["cards_message"] = update.message.text.strip()
    ctx.user_data["temp_cards"] = []
    await update.message.reply_text(
        "<b>Paso 3:</b> Ahora, envía las tarjetas. Puedes:\n\n"
        "1. Enviar una <b>foto, video o GIF</b> con los datos de la tarjeta en el pie de foto.\n"
        "2. Enviar un <b>mensaje de texto</b> con las tarjetas separadas por líneas.\n\n"
        "Cuando termines, envía el comando <code>/done</code>",
        parse_mode="HTML"
    )
    return AWAITING_CARDS_ACCOUNTS

async def receive_cards(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    caption = update.message.caption or update.message.text
    file_id = None
    file_type = None

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = 'photo'
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = 'video'
    elif update.message.animation:
        file_id = update.message.animation.file_id
        file_type = 'animation'
    elif update.message.text:
        file_id = None
        file_type = 'text'

    if not caption:
        await update.message.reply_text("❌ Por favor, envía los datos de la tarjeta en el pie de foto del archivo multimedia o en el mensaje de texto.")
        return AWAITING_CARDS_ACCOUNTS

    if file_type == 'text':
        cards = [card.strip() for card in caption.split('\n') if card.strip()]
        if not cards:
            await update.message.reply_text("❌ Por favor, envía al menos una tarjeta.")
            return AWAITING_CARDS_ACCOUNTS
        for card in cards:
            ctx.user_data["temp_cards"].append({"card": card, "file_id": None, "file_type": "text"})
        await update.message.reply_text(f"✅ Se agregaron {len(cards)} tarjetas. Envía más o usa /done para finalizar.")
    else:
        ctx.user_data["temp_cards"].append({"card": caption.strip(), "file_id": file_id, "file_type": file_type})
        await update.message.reply_text(f"✅ Tarjeta con {file_type} agregada. Envía otra o usa /done para finalizar.")

    return AWAITING_CARDS_ACCOUNTS

async def finish_add_cards(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    site = ctx.user_data.get("cards_site")
    message = ctx.user_data.get("cards_message")
    cards_to_add = ctx.user_data.get("temp_cards", [])

    if not cards_to_add:
        await update.message.reply_text("❌ No agregaste ninguna tarjeta. Operación cancelada.")
        return ConversationHandler.END

    cards = load_data(DB_CARDS, {})
    cards[site] = {"message": message, "cards": cards_to_add}
    save_data(DB_CARDS, cards)

    await update.message.reply_text(f"✅ Se han subido <b>{len(cards_to_add)}</b> tarjetas para <code>{site}</code> con éxito.", parse_mode="HTML")
    return ConversationHandler.END

# --- Promover/Degradar Admin (Solo para Super Admin) ---
@check_super_admin
async def add_admin_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("Por favor, envía el ID del usuario que quieres promover a admin.")
    return AWAITING_ADMIN_ID

@check_super_admin
async def add_admin_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        new_admin_id = int(update.message.text)
    except (ValueError, IndexError):
        await update.message.reply_text("❌ El ID del usuario debe ser un número. Intenta de nuevo o envía /cancel.")
        return AWAITING_ADMIN_ID

    admins = load_data(DB_ADMINS, default=[])
    if new_admin_id in admins:
        await update.message.reply_text("❌ Este usuario ya es un admin.")
    else:
        admins.append(new_admin_id)
        save_data(DB_ADMINS, admins)
        await update.message.reply_text(f"✅ Usuario con ID <code>{new_admin_id}</code> ha sido promovido a admin con éxito.", parse_mode="HTML")

    return ConversationHandler.END

@check_super_admin
async def rem_admin_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("Por favor, envía el ID del usuario que quieres degradar.")
    return AWAITING_REMOVE_ADMIN_ID

@check_super_admin
async def rem_admin_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        admin_to_remove = int(update.message.text)
    except (ValueError, IndexError):
        await update.message.reply_text("❌ El ID del usuario debe ser un número. Intenta de nuevo o envía /cancel.")
        return AWAITING_REMOVE_ADMIN_ID

    admins = load_data(DB_ADMINS, default=[])
    if admin_to_remove not in admins:
        await update.message.reply_text("❌ Este usuario no es un admin.")
    elif admin_to_remove == ADMIN:
        await update.message.reply_text("❌ No puedes degradar al super-admin.")
    else:
        admins.remove(admin_to_remove)
        save_data(DB_ADMINS, admins)
        await update.message.reply_text(f"✅ Usuario con ID <code>{admin_to_remove}</code> ha sido degradado con éxito.", parse_mode="HTML")

    return ConversationHandler.END

# --- Main function ---
def main():
    """Inicia el bot."""
    logging.info("🚀 Iniciando bot...")
    application = Application.builder().token(TOKEN).build()

    # Comandos de usuario
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("key", key_cmd))
    application.add_handler(CommandHandler("get", get_cmd))

    # Manejadores de Callback para botones
    application.add_handler(CallbackQueryHandler(return_to_start, pattern="^start_menu$"))
    application.add_handler(CallbackQueryHandler(show_profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(show_cmds, pattern="^cmds$"))
    application.add_handler(CallbackQueryHandler(show_admin_panel, pattern="^panel$"))
    application.add_handler(CallbackQueryHandler(show_stock_menu, pattern="^stock$"))
    application.add_handler(CallbackQueryHandler(show_cuentas_stock, pattern="^show_stock_cuentas$"))
    application.add_handler(CallbackQueryHandler(show_cards_stock, pattern="^show_stock_tarjetas$"))
    application.add_handler(CallbackQueryHandler(gen_cmd, pattern="^gen_cmd$"))
    application.add_handler(CallbackQueryHandler(super_pro_key_cmd, pattern="^super_pro_key$"))
    application.add_handler(CallbackQueryHandler(gen_cards_key_cmd, pattern="^gen_cards_key$"))
    application.add_handler(CallbackQueryHandler(users_cmd, pattern="^users_cmd$"))

    # Conversaciones
    conv_handler_broadcast = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_broadcast, pattern="^send_msg_cmd$")],
        states={
            BROADCAST_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_broadcast_content)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    conv_handler_add_stock = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_stock, pattern="^addstock_start$")],
        states={
            AWAITING_STOCK_SITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stock_site)],
            AWAITING_STOCK_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stock_message)],
            AWAITING_STOCK_ACCOUNTS: [
                MessageHandler(filters.ALL & ~filters.COMMAND, receive_accounts),
                CommandHandler("done", finish_add_stock)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    conv_handler_add_cards = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_cards, pattern="^addcards_start$")],
        states={
            AWAITING_CARDS_SITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cards_site)],
            AWAITING_CARDS_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cards_message)],
            AWAITING_CARDS_ACCOUNTS: [
                MessageHandler(filters.ALL & ~filters.COMMAND, receive_cards),
                CommandHandler("done", finish_add_cards)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    conv_handler_ban = ConversationHandler(
        entry_points=[CallbackQueryHandler(ban_user_start, pattern="^ban_user_start$")],
        states={
            AWAITING_USER_ID_TO_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_end)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    conv_handler_unban = ConversationHandler(
        entry_points=[CallbackQueryHandler(unban_user_start, pattern="^unban_user_start$")],
        states={
            AWAITING_USER_ID_TO_UNBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, unban_user_end)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    conv_handler_add_admin = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_admin_start, pattern="^add_admin_start$")],
        states={
            AWAITING_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_end)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    conv_handler_rem_admin = ConversationHandler(
        entry_points=[CallbackQueryHandler(rem_admin_start, pattern="^rem_admin_start$")],
        states={
            AWAITING_REMOVE_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, rem_admin_end)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    conv_handler_revoke_premium = ConversationHandler(
        entry_points=[CallbackQueryHandler(revoke_premium_start, pattern="^revoke_premium_start$")],
        states={
            AWAITING_USER_ID_TO_REVOKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, revoke_premium_end)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    application.add_handler(conv_handler_broadcast)
    application.add_handler(conv_handler_add_stock)
    application.add_handler(conv_handler_add_cards)
    application.add_handler(conv_handler_ban)
    application.add_handler(conv_handler_unban)
    application.add_handler(conv_handler_add_admin)
    application.add_handler(conv_handler_rem_admin)
    application.add_handler(conv_handler_revoke_premium)

    # Manejador para mensajes no reconocidos
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_unknown_messages))

    # Inicia el bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()