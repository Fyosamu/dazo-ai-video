# dazo-ai-video

An automated video pipeline: a topic is picked, the script and captions are
generated, the video is assembled and then uploaded to YouTube - scheduled on
GitHub Actions, with no server of its own.

Built on [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)
and extended with a Telegram bot and the scheduling around it.

## What one run produces

- the main **16:9** video
- a **9:16** short
- the thumbnail and every text the video was built from
- an upload to YouTube when the connection secrets are configured
- `api.log` as an artifact when something fails

A quality filter runs before publishing, so a short or broken render is never
uploaded.

## How it runs

| | |
| --- | --- |
| **Scheduled** | Three daily slots - 05:00 / 09:00 / 13:00 UTC (09:00 / 13:00 / 17:00 Tehran). The run picks one at random and, if that slot does not fire, the next slot the same day takes over. |
| **Manual** | **Actions - Run workflow** with an English topic, or none to draw one automatically. |
| **Local** | `start.bat` or `daily-video.bat` on Windows. |

Topics come from a bank of about 10,000 whose consumption is recorded in
`publish/used_topics.txt`, so nothing is reused while unused topics remain.

Each run is capped at **6 hours**; an 11-20 minute video takes roughly 2 to 4
of those.

## Layout

```
.github/workflows/make-video.yml   scheduling and the build/upload job
bot/                               Telegram bot, YouTube auth and upload,
                                   secrets helper, subtitle font
publish/                           last upload and topics already used
caption.txt hook.txt script.txt    texts of the current render
start.bat daily-video.bat          local Windows launchers
```

`bot/README-FA.md` is the Persian write-up of the bot.

## Part of dazo

**[dazo](https://fyosamu.github.io/)** - AI, automation and web work.

[AI and automation](https://fyosamu.github.io/ai-automation/) -
[Pricing](https://fyosamu.github.io/pricing/) -
[hkay7645@gmail.com](mailto:hkay7645@gmail.com)
