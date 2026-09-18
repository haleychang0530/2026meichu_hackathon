#!/usr/bin/env python3
"""Generate a deterministic, redistributable Stage 02 textbook-image fixture set."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


W, H = 1280, 1600
BG = "#fffdf5"
INK = "#17202a"
ACCENT = "#d35400"


CASES = [
    {
        "id": "01_frontal_market",
        "condition": "frontal",
        "topic": "去市場",
        "source_text": "阿媽欲去市場買菜。",
        "tailo": "A-má beh khì tshī-tiûnn bé tshài.",
        "scene": "阿媽在市場向菜販買菜，囡仔站在旁邊。",
        "activity": "看圖講看覓：啥人咧買菜？",
        "objective": "辨識人物與動作，練習市場詞彙。",
    },
    {
        "id": "02_tilt_school",
        "condition": "tilt",
        "topic": "去學校",
        "source_text": "小明揹冊包去學校。",
        "tailo": "Sió-bîng phāinn tsheh-pau khì ha̍k-hāu.",
        "scene": "學生揹著書包走向校門。",
        "activity": "看圖回答：小明欲去佗位？",
        "objective": "理解地點與移動方向。",
    },
    {
        "id": "03_glare_weather",
        "condition": "glare",
        "topic": "落雨天",
        "source_text": "今仔日落雨，愛紮雨傘。",
        "tailo": "Kin-á-ji̍t lo̍h-hōo, ài tsah hōo-suànn.",
        "scene": "一位囡仔在雨中撐傘，地面有水窟。",
        "activity": "揀看覓：落雨天愛帶啥物？",
        "objective": "連結天氣與合適物品。",
    },
    {
        "id": "04_dense_tailo",
        "condition": "dense_tailo",
        "topic": "果子",
        "source_text": "蘋果甜甜，柑仔芳芳，弓蕉軟軟。",
        "tailo": "Phông-kó tinn-tinn, kam-á phang-phang, king-tsio nńg-nńg.",
        "scene": "三格小圖分別畫蘋果、柑仔與弓蕉。",
        "activity": "對看覓：果子佮滋味配做伙。",
        "objective": "辨識果物詞彙與形容詞。",
    },
    {
        "id": "05_illustration_choice",
        "condition": "illustration",
        "topic": "動物的聲",
        "source_text": "狗仔吠，貓仔喵，雞仔啼。",
        "tailo": "Káu-á puī, niau-á niau, ke-á thî.",
        "scene": "三隻動物排成一列：狗、貓、雞。",
        "activity": "聽聲揀圖：啥物動物咧喵？",
        "objective": "配對動物與叫聲。",
    },
    {
        "id": "06_dialogue_bubbles",
        "condition": "dialogue",
        "topic": "食晝",
        "source_text": "阿珍：你欲食啥物？\n阿華：我欲食滷肉飯。",
        "tailo": "A-Tin: Lí beh tsia̍h siánn-mih?\nA-Huâ: Guá beh tsia̍h lóo-bah-pn̄g.",
        "scene": "兩位學生在餐桌前對話。",
        "activity": "兩人一組，照對話換一項食物。",
        "objective": "練習詢問與回答想吃的食物。",
    },
    {
        "id": "07_low_contrast",
        "condition": "low_contrast",
        "topic": "做家事",
        "source_text": "阿兄摒掃，阿姊拭桌。",
        "tailo": "A-hiann piànn-sàu, a-tsí tshit toh.",
        "scene": "客廳裡，一人掃地，另一人擦桌。",
        "activity": "講看覓：逐家咧做啥物代誌？",
        "objective": "辨識家事動作與人物。",
    },
    {
        "id": "08_two_column",
        "condition": "two_column",
        "topic": "身軀部位",
        "source_text": "目睭看，耳仔聽，喙講話，手提物件。",
        "tailo": "Ba̍k-tsiu khuànn, hīnn-á thiann, tshuì kóng-uē, tshiú the̍h mi̍h-kiānn.",
        "scene": "左欄是身體部位圖，右欄是功能配對題。",
        "activity": "連看覓：身軀部位佮功能。",
        "objective": "配對身體部位與感官或動作功能。",
    },
    {
        "id": "09_picture_reasoning",
        "condition": "picture_question",
        "topic": "過馬路",
        "source_text": "紅燈停，青燈行，過路愛細膩。",
        "tailo": "Âng-ting thîng, tshenn-ting kiânn, kuè-lōo ài sè-jī.",
        "scene": "路口號誌是紅燈，一位囡仔站在人行道邊等待。",
        "activity": "看圖判斷：這馬會當過路無？講出理由。",
        "objective": "依交通號誌判斷安全行動並說明理由。",
    },
    {
        "id": "10_mixed_annotations",
        "condition": "mixed",
        "topic": "四季",
        "source_text": "春天花開，熱天食冰，秋天風涼，寒天穿厚衫。",
        "tailo": "Tshun-thinn hue khui, jua̍h-thinn tsia̍h ping, tshiu-thinn hong liâng, kuânn-thinn tshīng kāu-sann.",
        "scene": "四個插圖分別表示春、夏、秋、冬，旁邊有手寫圈選。",
        "activity": "看圖配對季節佮活動，閣講你上佮意佗一季。",
        "objective": "辨識季節特徵並表達偏好。",
    },
]


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def fit_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fnt, width: int, fill=INK, spacing=12):
    x, y = xy
    line = ""
    lines: list[str] = []
    for ch in text:
        trial = line + ch
        if draw.textbbox((0, 0), trial, font=fnt)[2] > width and line:
            lines.append(line)
            line = ch
        else:
            line = trial
    lines.append(line)
    for item in lines:
        draw.text((x, y), item, font=fnt, fill=fill)
        y += fnt.size + spacing
    return y


def draw_people(draw: ImageDraw.ImageDraw, kind: str):
    draw.rounded_rectangle((120, 650, 1160, 1080), 28, fill="#eaf2f8", outline="#5dade2", width=5)
    if kind == "illustration":
        for x, label, color in [(330, "狗", "#d7bde2"), (640, "貓", "#f9e79f"), (950, "雞", "#f5b7b1")]:
            draw.ellipse((x - 105, 735, x + 105, 945), fill=color, outline=INK, width=5)
            draw.text((x - 32, 960), label, font=draw._font_body, fill=INK)
    elif kind == "dialogue":
        for x, color in [(380, "#fadbd8"), (900, "#d6eaf8")]:
            draw.ellipse((x - 70, 820, x + 70, 960), fill=color, outline=INK, width=4)
            draw.line((x, 960, x, 1040), fill=INK, width=8)
        draw.rounded_rectangle((180, 680, 590, 810), 25, fill="white", outline=INK, width=4)
        draw.rounded_rectangle((690, 680, 1100, 810), 25, fill="white", outline=INK, width=4)
        draw.text((225, 720), "你欲食啥物？", font=draw._font_small, fill=INK)
        draw.text((735, 720), "我欲食滷肉飯。", font=draw._font_small, fill=INK)
    else:
        for x, color in [(390, "#f5cba7"), (820, "#aed6f1")]:
            draw.ellipse((x - 75, 760, x + 75, 910), fill=color, outline=INK, width=4)
            draw.line((x, 910, x, 1040), fill=INK, width=8)
            draw.line((x, 950, x - 80, 1010), fill=INK, width=7)
            draw.line((x, 950, x + 80, 1010), fill=INK, width=7)


def make_page(case: dict, font_path: Path) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(im)
    title_f = font(font_path, 62)
    body_f = font(font_path, 44)
    small_f = font(font_path, 34)
    tailo_f = font(font_path, 36)
    draw._font_body = body_f
    draw._font_small = small_f
    draw.rounded_rectangle((50, 45, 1230, 1550), 28, outline="#566573", width=5)
    draw.rectangle((50, 45, 1230, 165), fill="#fdebd0")
    draw.text((90, 70), case["topic"], font=title_f, fill=ACCENT)
    y = fit_text(draw, (90, 220), case["source_text"], body_f, 1090)
    y = fit_text(draw, (90, y + 20), case["tailo"], tailo_f, 1090, fill="#1f618d")
    draw_people(draw, case["condition"])
    draw.rounded_rectangle((90, 1130, 1190, 1325), 22, fill="#fcf3cf", outline="#b7950b", width=4)
    fit_text(draw, (120, 1160), case["activity"], small_f, 1030)
    draw.text((95, 1390), "學習重點", font=small_f, fill=ACCENT)
    fit_text(draw, (300, 1390), case["objective"], small_f, 850)

    condition = case["condition"]
    if condition == "tilt":
        rotated = im.rotate(7.5, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="#777777")
        left = (rotated.width - W) // 2
        top = (rotated.height - H) // 2
        im = rotated.crop((left, top, left + W, top + H))
    elif condition == "glare":
        glare = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glare)
        gd.polygon([(720, 0), (1160, 0), (800, H), (400, H)], fill=(255, 255, 255, 105))
        glare = glare.filter(ImageFilter.GaussianBlur(28))
        im = Image.alpha_composite(im.convert("RGBA"), glare).convert("RGB")
    elif condition == "low_contrast":
        im = ImageEnhance.Contrast(im).enhance(0.52).filter(ImageFilter.GaussianBlur(0.7))
    elif condition == "two_column":
        d = ImageDraw.Draw(im)
        d.line((640, 650, 640, 1080), fill="#85929e", width=5)
    elif condition == "mixed":
        d = ImageDraw.Draw(im)
        d.ellipse((865, 1370, 1170, 1490), outline="#c0392b", width=9)
        d.line((1060, 1360, 1175, 1320), fill="#c0392b", width=8)
    return im


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("dataset"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": "stage02-dataset.v1", "width": W, "height": H, "cases": []}
    for case in CASES:
        image = make_page(case, args.font)
        path = args.output / f"{case['id']}.png"
        image.save(path, format="PNG", optimize=True)
        manifest["cases"].append({**case, "file": path.name})
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated {len(CASES)} images in {args.output}")


if __name__ == "__main__":
    main()
