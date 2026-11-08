# Проверка доступа к официальным архивам из Linux

Это однократная проверка доступности источников с собственного Linux-сервера. В GitHub Actions архивы Кремля недоступны из-за тайм-аутов, а сайт президента Украины возвращает 403 при проверке robots.txt. Другая сеть может иметь иной технический результат, однако это не отменяет ограничений сайта и лицензий.

Для этой проверки GPU, CUDA, root и учётные данные внешних сайтов не нужны. Выполняется только чтение DNS, HTTPS и robots.txt, без обхода отказов и без массовой выгрузки.

## Быстрый тест (в терминале Ubuntu)

    getent ahosts kremlin.ru | head -3
    getent ahosts www.president.gov.ua | head -3
    for host in https://kremlin.ru https://news.kremlin.ru https://www.president.gov.ua https://president.gov.ua; do
      echo "=== $host ==="
      curl -sS -L --connect-timeout 8 --max-time 20 -o /dev/null \
        -w 'HTTP %{http_code}; total %{time_total}s; final %{url_effective}\n' "$host/robots.txt" || true
    done

## Проверка кодом проекта

    git clone https://github.com/2001092236/Emotional-tone-of-the-text.git
    cd Emotional-tone-of-the-text
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements-dev.txt
    python -m corpus2026.official_probe --out /tmp/mgimo_official_source_probe.json
    python -m json.tool /tmp/mgimo_official_source_probe.json

Эта команда проверяет настроенные официальные индексные URL и HTTPS-редиректы с учётом robots.txt. Она не сохраняет тексты. Используется отдельная среда Python и временный путь в /tmp, без изменения существующих приложений и без использования GPU.

Если robots.txt возвращает 403 либо disallow, массовый сбор не запускаем. Если есть DNS-ошибка или тайм-аут — диагностируем сеть, но не делаем выводов о правах. Если доступ к индексу разрешён, отдельно проверяем конкретные статьи и права, и лишь затем можно выполнить исторический импорт за 2026 год. Не считать сообщения пресс-службы прямой речью Путина. Оригинальные украинские тексты Зеленского не смешивать с английскими переводами.

Скрипты нельзя запускать в обход CAPTCHA, авторизации, robots.txt или ограничений сайтов. Никакого cron или фонового процесса нет.
