# Kariz panel

پنل سبک Kariz — stdlib پایتون، بدون وابستگی. نصب **یک خط**، بقی کارها داخل پنل.

## نصب یک خط (روی ماشین پنل)

```bash
curl -fsSL https://raw.githubusercontent.com/Hosein21378/kariz-panel/main/install.sh | bash
```

اسکریپت: `python3` چک میکند، `panel.py` میگیرند، سرویس `kariz-panel` را فعالمیکند،
آدرس + یوزر + پسورد تصادفی چاپ میکند. state در `/var/lib/kariz-panel/panel.db`.

> برای میزبان/فورک دیگر `KARIZ_BASE` را ست کن (پایین). تست محلی با `--from-dir` کار میکند.

## داخل پنل (همه کارها اینجا)

1. **Add server** → پنل یک join code میدهد + **یک خط کد** برای سرور هدف.
2. روی سرور هدف همان یک خط را اجرا میکنی — agent وصل میشود، نیازی به پورت باز نیست.
3. **Tunnels** → entry / exit / پورت تونل / transport / لیست forward (listen → target).
4. agent هر ۳۰ ثانیه کانفیگ را میکشد، `/etc/kariz/<name>.toml` مینویسد،
   `kariz@<name>` را enable/restart میکند. حذف از پنل = حذف تونل از سرور بعدی پول.

پورت forward از پنل تعریف میشود، نه با دستور.

## متغیرها (اختیاری)

| متغیر | پیش فرض | کار |
|---|---|---|
| `KARIZ_PANEL_PORT` | `28443` | پورت وب پنل |
| `KARIZ_PANEL_USER` / `KARIZ_PANEL_PASS` | `admin` / تصادفی |Basic auth |
| `KARIZ_PANEL_DB` | `/var/lib/kariz-panel/panel.db` | فایل state |
| `KARIZ_JOIN` / `KARIZ_PANEL` | — | agent: توکن و آدرس پنل |
| `KARIZ_INTERVAL` | `30` | فاصله pull agent (ثانیه) |
| `KARIZ_DIR` | `/etc/kariz` | محل TOMLها |
| `KARIZ_BASE` | raw GitHub | منبع دانلود اسکریپت/فایلها |

## تست محلی (بدون سرور، بدون systemd)

```bash
cd /root/kariz-panel
KARIZ_PANEL_DB=./panel.db KARIZ_PANEL_PORT=28999 python3 panel.py &
# UI: http://127.0.0.1:28999
bash install.sh --from-dir /root/kariz-panel --no-service --port 28999
```

## ساختار

- `panel.py` — API + UI +生成的 TOML (entry/exit)
- `agent.py` — join / pull / write / restart
- `install.sh` — نصب یک خط (پنل یا agent با `--join`)
- `/etc/systemd/system/kariz-panel.service`، `kariz-agent.service`

هیچ تغییری روی سرورهای France/Iran/Turkey اعمال نشده.
