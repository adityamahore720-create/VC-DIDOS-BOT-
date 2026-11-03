const { Redis } = require("@upstash/redis");

const redis = Redis.fromEnv();
const BOT_TOKEN = process.env.BOT_TOKEN;

async function tg(method, body) {
  const r = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  return r.json();
}

async function send(chatId, text, keyboard) {
  const body = { chat_id: chatId, text, disable_web_page_preview: true };
  if (keyboard) body.reply_markup = { inline_keyboard: keyboard };
  return tg("sendMessage", body);
}

const key = (chat, name) => `nxc:${chat}:${name}`;

async function mainMenu(chatId) {
  return send(chatId,
    "NXC MULTI MANAGER\n\nReport drafts aur targets ko organize karo. Reports Telegram par manually submit hongi.",
    [
      [{ text: "➕ Add Target", callback_data: "add_target" },
       { text: "📋 My Targets", callback_data: "targets" }],
      [{ text: "📝 Add Report Form", callback_data: "add_form" },
       { text: "📚 Saved Forms", callback_data: "forms" }],
      [{ text: "ℹ️ Help", callback_data: "help" }]
    ]);
}

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(200).send("NXC bot webhook is running.");
  if (!BOT_TOKEN) return res.status(500).send("BOT_TOKEN is missing.");

  try {
    const update = req.body || {};
    const msg = update.message;
    const cb = update.callback_query;

    if (cb) {
      const chatId = cb.message.chat.id;
      const userId = cb.from.id;
      const action = cb.data;
      await tg("answerCallbackQuery", { callback_query_id: cb.id });

      if (action === "home") return await mainMenu(chatId), res.status(200).send("ok");
      if (action === "add_target") {
        await redis.set(key(userId, "state"), "target");
        await send(chatId, "Channel/group ka naam aur ID ek message mein bhejo.\nExample: My Channel | -1001234567890");
      } else if (action === "targets") {
        const items = await redis.lrange(key(userId, "targets"), 0, 49);
        await send(chatId, items.length ? "Saved targets:\n\n" + items.map((x, i) => `${i + 1}. ${x}`).join("\n") : "Abhi koi target saved nahi hai.");
      } else if (action === "add_form") {
        await redis.set(key(userId, "state"), "form");
        await send(chatId, "Report form ka naam aur message bhejo. Format:\nForm Name | Report reason/message");
      } else if (action === "forms") {
        const items = await redis.lrange(key(userId, "forms"), 0, 49);
        await send(chatId, items.length ? "Saved report forms:\n\n" + items.map((x, i) => `${i + 1}. ${x}`).join("\n\n") : "Abhi koi form saved nahi hai.");
      } else if (action === "help") {
        await send(chatId, "Commands:\n/start — main menu\n/target — target save karo\n/form — report form save karo\n/targets — saved targets dekho\n/forms — saved forms dekho\n\nYeh bot sirf details aur report drafts organize karta hai. Telegram par report tum khud review karke submit karoge.");
      }
      return res.status(200).send("ok");
    }

    if (msg) {
      const chatId = msg.chat.id;
      const userId = msg.from.id;
      const text = (msg.text || "").trim();

      if (text === "/start") {
        await redis.del(key(userId, "state"));
        await mainMenu(chatId);
      } else if (text === "/target") {
        await redis.set(key(userId, "state"), "target");
        await send(chatId, "Target bhejo: Channel/Group Name | ID");
      } else if (text === "/form") {
        await redis.set(key(userId, "state"), "form");
        await send(chatId, "Form bhejo: Form Name | Report reason/message");
      } else if (text === "/targets" || text === "/forms") {
        const listName = text === "/targets" ? "targets" : "forms";
        const items = await redis.lrange(key(userId, listName), 0, 49);
        await send(chatId, items.length ? items.map((x, i) => `${i + 1}. ${x}`).join("\n\n") : "List abhi empty hai.");
      } else {
        const state = await redis.get(key(userId, "state"));
        if (state === "target" || state === "form") {
          if (!text.includes("|") || text.split("|").length < 2) {
            await send(chatId, "Format mein | zaroor lagao.\nExample: My Channel | -1001234567890");
          } else {
            const listName = state === "target" ? "targets" : "forms";
            await redis.lpush(key(userId, listName), text.slice(0, 1000));
            await redis.ltrim(key(userId, listName), 0, 49);
            await redis.del(key(userId, "state"));
            await send(chatId, state === "target" ? "Target save ho gaya." : "Report form save ho gaya.", [[{ text: "Main Menu", callback_data: "home" }]]);
          }
        } else {
          await send(chatId, "Menu ke liye /start bhejo.");
        }
      }
    }
    return res.status(200).send("ok");
  } catch (e) {
    console.error(e);
    return res.status(200).send("ok");
  }
}
