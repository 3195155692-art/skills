"use strict";
/**
 * deck_kit.js — the rounded-card deck kit used by LKY report decks.
 *
 * The caller supplies pptxgenjs, because its path depends on the machine's bundled runtime
 * (see load_workspace_dependencies). Everything else is set up here.
 *
 *   const pptxgen = require("<node-runtime>/node_modules/pptxgenjs");
 *   const kit = require("./deck_kit")(pptxgen, { cjk: "Heiti SC", latin: "Times New Roman" });
 *   const { pres, C, t, card, accentTop, slide_light, header, conclusionBand, notes } = kit;
 *
 * Two invariants worth keeping:
 *   - every rectangle is rounded, and colour accents are capsules inset inside their card
 *     so they never poke past a rounded corner;
 *   - a run that contains CJK is never allowed onto the Latin-only face.
 */

const path = require("path");

module.exports = function createKit(pptxgen, opts = {}) {
  if (!pptxgen || typeof pptxgen !== "function") {
    throw new Error(
      "createKit(pptxgen, ...) needs the pptxgenjs module. " +
        "Find it under the bundled Node runtime's node_modules and require it by absolute path."
    );
  }

  // ---------------------------------------------------------------- design tokens
  const F = opts.cjk || "Heiti SC";
  const FL = opts.latin || "Times New Roman";
  const SIZE = opts.scale === undefined ? 1.09 : opts.scale;
  const RADIUS = opts.radius === undefined ? 0.13 : opts.radius;
  const ASSETS = opts.assets || path.join(__dirname, "..", "assets");

  const C = {
    ink: "0A1A2F",
    inkSoft: "13293F",
    inkLine: "24405C",
    navy: "17527A",
    navyDeep: "0F3A57",
    navyPale: "E7EFF6",
    cyan: "2FB8C6",
    cyanDeep: "1B8C99",
    cyanPale: "DCF1F3",
    amber: "D98A21",
    amberPale: "FCEEDA",
    paper: "F5F8FB",
    card: "FFFFFF",
    line: "DCE5EE",
    text: "16222E",
    sub: "5A6B7D",
    onDark: "EAF2F8",
    onDarkSub: "9FB4C7",
    alert: "E07A5F",
  };

  const W = 13.333;
  const H = 7.5;
  const M = 0.62;
  const CW = W - 2 * M;
  const CJK_RE = /[\u4e00-\u9fff]/;
  const uk = (v) => Math.round(v * SIZE * 2) / 2;
  // 12 pt is the floor for anything that reaches the room, and body text runs at 1.5 line
  // spacing. Both are enforced here rather than trusted to the caller.
  const MIN_SIZE = opts.minSize === undefined ? 12 : opts.minSize;
  const LINE_MULTIPLE = opts.lineMultiple === undefined ? 1.5 : opts.lineMultiple;
  const fs = (v) => Math.max(MIN_SIZE, uk(v));

  const pres = new pptxgen();
  pres.defineLayout({ name: "DECK16x9", width: W, height: H });
  pres.layout = "DECK16x9";

  let pageNo = 0;

  // ---------------------------------------------------------------- primitives
  function card(slide, x, y, w, h, o = {}) {
    slide.addShape(pres.ShapeType.roundRect, {
      x,
      y,
      w,
      h,
      rectRadius: o.radius === undefined ? RADIUS : o.radius,
      fill: { color: o.fill || C.card },
      line: { color: o.line || C.line, width: o.lineW === undefined ? 1 : o.lineW },
    });
  }

  /** A fully rounded bar/capsule; `h` (or `w`) is the thickness. */
  function pill(slide, x, y, w, h, color) {
    slide.addShape(pres.ShapeType.roundRect, {
      x,
      y,
      w,
      h,
      rectRadius: Math.min(w, h) / 2,
      fill: { color },
      line: { color, width: 0 },
    });
  }

  /** Hairline / divider. Rounded so no sharp corner survives anywhere in the deck. */
  function bar(slide, x, y, w, h, color) {
    pill(slide, x, y, w, h, color);
  }

  /** Edge-to-edge strip that must stay square (cover and act dividers only). */
  function sharpBar(slide, x, y, w, h, color) {
    slide.addShape(pres.ShapeType.rect, {
      x,
      y,
      w,
      h,
      fill: { color },
      line: { color, width: 0 },
    });
  }

  /** Colour accent tucked inside a card's top edge, clear of the rounded corners. */
  function accentTop(slide, x, y, w, color) {
    pill(slide, x + 0.15, y + 0.1, w - 0.3, 0.08, color);
  }

  /** Colour accent tucked inside a card's left edge. */
  function accentLeft(slide, x, y, h, color) {
    pill(slide, x + 0.12, y + 0.14, 0.075, Math.max(0.16, h - 0.28), color);
  }

  function t(slide, text, x, y, w, h, o = {}) {
    // A latin-only face must never carry CJK glyphs: PowerPoint looks for them in that
    // font's East Asian slot, fails, and renders boxes. Promote such runs to the CJK face.
    let face = o.face || F;
    if (face === FL && CJK_RE.test(String(text))) face = F;
    slide.addText(text, {
      x,
      y,
      w,
      h,
      fontFace: face,
      fontSize: fs(o.size || 12),
      color: o.color || C.text,
      bold: !!o.bold,
      italic: !!o.italic,
      align: o.align || "left",
      valign: o.valign || "top",
      lineSpacing: o.line ? uk(o.line) : undefined,
      // spacing only means something once a paragraph wraps; ask for it when the text has
      // a hard break, so one-line labels keep their natural height
      lineSpacingMultiple:
        o.line || !/\n/.test(String(text)) ? undefined : (o.lineMultiple || LINE_MULTIPLE),
      paraSpaceAfter: o.after === undefined ? undefined : o.after,
      charSpacing: o.spacing === undefined ? undefined : o.spacing,
      margin: o.margin === undefined ? 0 : o.margin,
      isTextBox: true,
      shrinkText: false,
    });
  }

  function bullets(slide, items, x, y, w, h, o = {}) {
    const arr = items.map((it, i) => {
      const isStr = typeof it === "string";
      const last = i === items.length - 1;
      return {
        text: isStr ? it : it.text,
        options: Object.assign(
          {
            bullet: o.bullet === undefined ? { code: "2022", indent: 14 } : o.bullet,
            breakLine: !last, // a trailing empty bullet appears otherwise
            color: o.color || C.text,
            fontSize: fs(o.size || 12.5),
            fontFace: o.face || F,
            lineSpacing: o.line ? uk(o.line) : undefined,
            lineSpacingMultiple: o.line ? undefined : (o.lineMultiple || LINE_MULTIPLE),
            paraSpaceAfter: o.after === undefined ? 6 : o.after,
            bold: !!(isStr ? o.bold : it.bold),
          },
          isStr ? {} : it.options || {}
        ),
      };
    });
    slide.addText(arr, {
      x,
      y,
      w,
      h,
      valign: o.valign || "top",
      margin: 0,
      isTextBox: true,
      shrinkText: false,
    });
  }

  function notes(slide, text) {
    slide.addNotes(text);
  }

  // ---------------------------------------------------------------- page furniture
  function header(slide, eyebrow, title, o = {}) {
    const dark = !!o.dark;
    slide.addImage({
      path: path.join(ASSETS, "wave_mark.png"),
      x: M,
      y: 0.46,
      w: 1.5,
      h: 0.42,
    });
    t(slide, eyebrow, M + 1.72, 0.42, CW - 3.2, 0.34, {
      size: 10.5,
      bold: true,
      spacing: 1.4,
      color: dark ? C.cyan : C.cyanDeep,
      valign: "middle",
    });
    pageNo += 1;
    t(slide, String(pageNo).padStart(2, "0"), W - M - 1.2, 0.42, 1.2, 0.34, {
      size: 10.5,
      face: FL,
      bold: true,
      color: dark ? C.onDarkSub : C.sub,
      align: "right",
      valign: "middle",
    });
    t(slide, title, M, 0.86, CW, 0.72, {
      size: o.size || 27,
      bold: true,
      color: dark ? C.onDark : C.navyDeep,
      valign: "middle",
    });
    pill(slide, M, 1.66, CW, 0.028, dark ? C.inkLine : C.line);
  }

  function footnote(slide, text, o = {}) {
    t(slide, text, o.x === undefined ? M : o.x, o.y === undefined ? 6.98 : o.y, o.w || CW, 0.3, {
      size: 9,
      color: o.color || C.sub,
      valign: "bottom",
    });
  }

  function slide_light(eyebrow, title, o) {
    const s = pres.addSlide();
    s.background = { color: C.paper };
    header(s, eyebrow, title, o);
    return s;
  }

  function slide_dark(eyebrow, title, o) {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    header(s, eyebrow, title, Object.assign({ dark: true }, o));
    return s;
  }

  /** Full-bleed dark page that opens one act of the talk. */
  function actDivider(num, title, en, lead, points) {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    s.addImage({ path: path.join(ASSETS, "wave_dark.png"), x: -0.3, y: 5.35, w: 13.95, h: 2.6 });
    sharpBar(s, 0, 0, W, 0.11, C.cyan);
    t(s, `第 ${num} 幕`, M, 1.46, 3.0, 0.4, {
      size: 13,
      bold: true,
      spacing: 2.4,
      color: C.cyan,
    });
    t(s, title, M, 1.9, 8.2, 1.0, { size: 40, bold: true, color: C.onDark });
    t(s, en, M, 2.96, 8.6, 0.4, { size: 13, face: FL, color: C.onDarkSub });
    pill(s, M, 3.56, 2.3, 0.04, C.amber);
    t(s, lead, M, 3.84, 8.3, 1.6, { size: 14, color: C.onDark, line: 21 });

    card(s, M + 8.8, 1.9, CW - 8.8, 3.54, { fill: C.inkSoft, line: C.inkLine });
    t(s, "这一幕要交代的问题", M + 9.1, 2.1, CW - 9.42, 0.32, {
      size: 11.5,
      bold: true,
      color: C.cyan,
    });
    points.forEach((p, i) => {
      t(s, `0${i + 1}`, M + 9.1, 2.5 + i * 0.96, 0.46, 0.36, {
        size: 12,
        face: FL,
        bold: true,
        color: C.amber,
      });
      t(s, p, M + 9.6, 2.48 + i * 0.96, CW - 9.92, 0.88, {
        size: 11,
        color: C.onDark,
        line: 15.5,
      });
    });
    return s;
  }

  /** The one-line takeaway that closes each paper. */
  function conclusionBand(slide, text, o = {}) {
    const bx = o.x === undefined ? M : o.x;
    const by = o.y === undefined ? 6.14 : o.y;
    const bw = o.w === undefined ? CW : o.w;
    const bh = o.h === undefined ? 0.9 : o.h;
    const fill = o.fill || C.navyDeep;
    card(slide, bx, by, bw, bh, { fill, line: o.line || fill });
    t(slide, "汇报结论", bx + 0.32, by, 1.42, bh, {
      size: 11,
      bold: true,
      spacing: 1.2,
      color: C.cyan,
      valign: "middle",
    });
    t(slide, text, bx + 1.82, by, bw - 2.14, bh, {
      size: 12,
      bold: true,
      color: C.onDark,
      valign: "middle",
      line: 16.5,
    });
    return slide;
  }

  function stat(slide, big, label, x, y, w, o = {}) {
    t(slide, big, x, y, w, o.bigH || 1.0, {
      size: o.bigSize || 52,
      face: o.face || F,
      bold: true,
      color: o.bigColor || C.navy,
      valign: "bottom",
    });
    t(slide, label, x, y + (o.bigH || 1.0) - 0.02, w, o.labelH || 0.62, {
      size: o.labelSize || 11,
      color: o.labelColor || C.sub,
      line: 14.5,
    });
  }

  /** Write the deck and report what was produced. */
  async function write(file, meta = {}) {
    pres.author = meta.author || pres.author;
    pres.title = meta.title || pres.title;
    pres.subject = meta.subject || pres.subject;
    const out = await pres.writeFile({ fileName: file });
    const fs = require("fs");
    console.log(`written: ${out}  (${Math.round(fs.statSync(file).size / 1024)} KB, ${pageNo} numbered pages)`);
    return out;
  }

  return {
    pres,
    C,
    F,
    FL,
    SIZE,
    RADIUS,
    ASSETS,
    W,
    H,
    M,
    CW,
    card,
    pill,
    bar,
    sharpBar,
    accentTop,
    accentLeft,
    t,
    bullets,
    notes,
    header,
    footnote,
    slide_light,
    slide_dark,
    actDivider,
    conclusionBand,
    stat,
    write,
  };
};
