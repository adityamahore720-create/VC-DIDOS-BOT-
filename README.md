# NXC MULTI MANAGER — Vercel

A Telegram bot to save channel/group targets and custom report-form drafts.
It does **not** log into Telegram user accounts, collect OTP/passwords, or
send/coordinate reports. Review and submit any report yourself through
Telegram's official reporting interface.

## 1. Create the bot
1. Open Telegram and message `@BotFather`.
2. Run `/newbot` and copy the bot token.
3. Never share the token publicly.

## 2. Create persistent storage
1. Create a free Upstash Redis database.
2. Copy its REST URL and REST token.

## 3. Deploy to Vercel
1. Upload this project to a GitHub repository.
2. Import that repository in Vercel.
3. Add these Environment Variables in Vercel:
   - `BOT_TOKEN`
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`
4. Deploy and copy your deployment URL, for example:
   `https://your-project.vercel.app`

## 4. Set Telegram webhook
Open this URL in your browser, replacing the values:

`https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook?url=https://YOUR_PROJECT.vercel.app/api/webhook`

Telegram should return `{"ok":true,"result":true,...}`.

## Commands
- `/start` — open menu
- `/target` — save a channel/group as `Name | ID`
- `/form` — save a report draft as `Form Name | Report message`
- `/targets` — show saved targets
- `/forms` — show saved report drafts

## Notes
- This is a basic personal bot; it does not provide unlimited Telegram-account login.
- Do not enter Telegram account passwords or login OTPs into this bot.
- Saved report forms are drafts for manual review, not automatic reports.
