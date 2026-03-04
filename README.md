# PixelArtMCP

PixelArtMCP теперь поддерживает работу как **MCP server** и как старый TCP/CLI инструмент.

## Запуск MCP-сервера

```bash
python pxart.py mcp --size 64x64 --name demo
```

Сервер поднимается по stdio и предоставляет инструменты:

- `list_commands` — список всех доступных команд рисования.
- `run_command` — универсальный tool-обертка для всех функций (`set_pixel`, `fill_rect`, `gradient_rect`, `paste_image_region`, `export_png`, и т.д.).
- `status` — текущий статус проекта.
- `screenshot` — сохранить PNG-скриншот текущего вида канваса.

## GUI при работе через MCP

Можно включить GUI, чтобы видеть, что делает модель:

```bash
python pxart.py mcp --config mcp_config.json
```

`mcp_config.json`:

```json
{
  "show_gui": true
}
```

Или принудительно:

```bash
python pxart.py mcp --gui
```

Внизу окна отображается последняя активность (например, команды от `[mcp]`).

## Новые команды рисования

- `gradient_rect <x> <y> <w> <h> <start_color> <end_color> [direction]`
  - `direction`: `horizontal` / `vertical` / `diagonal`
- `set_background_reference <path> [opacity] [offset_x] [offset_y]`
- `clear_background_reference`
- `paste_image_region <path> <src_x> <src_y> <w> <h> <dest_x> <dest_y>`
- `capture_screenshot <path> [zoom]`

## Старый режим

Старый TCP-режим с `python pxart.py start` и CLI-командами сохранен.
