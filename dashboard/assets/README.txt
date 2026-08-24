Brand assets for the dashboard
==============================

The top bar mark is loaded by the brand() function in index.html, which tries the
filenames in its `tries` list in order and uses the first that loads.

It currently reads, in order:

    Lloyds_Banking_Group_Logo.png     (in dashboard/, this is the one in use)
    Lloyds-Bank-Symbol.png            (in dashboard/, fallback)

If neither loads the chip removes itself, so there is no empty white box.

To use a different mark, put the file next to index.html and add its filename to the
FRONT of that list. Do not rely on a naming convention: the list is probed with real
requests, so any name in it that is not on disk costs a 404 on every page load. That
is exactly what happened with the earlier "assets/lloyds-logo.svg" and
"assets/lloyds-logo.png" entries, which were documented here but never added.

The mark sits inside a white rounded chip, because the official horse is black and the
top bar is dark green. That keeps the asset unmodified, which is what brand guidelines
normally require. Do not recolour the supplied file.

horse-mark.png in this folder is the watermark silhouette used behind the hero and the
empty state, not the top-bar mark.


Headline font
=============

fraunces-latin.woff2 and fraunces-latin-ext.woff2 are the heading typeface, declared in
the @font-face block at the top of index.html's stylesheet and referenced by the
--font-display token. Two subsets, split by unicode-range: the browser fetches latin-ext
only when a heading actually contains an accented character, which on most pages is
never.

They are SELF-HOSTED on purpose. The dashboard makes no external network requests at
all, and a demo that loses its typography when the room's wifi drops is not one worth
giving. Do not replace these with a Google Fonts <link>.

Why Fraunces and not the real thing: Lloyds' headline face is GT Ultra Lloyds, a custom
cut of Grilli Type's GT Ultra. Custom cuts are not sold, the licence belongs to Lloyds,
and there is no legitimate way to obtain it except from the bank. The retail GT Ultra is
a paid Grilli Type licence. Fraunces is the closest open-licensed face to what GT Ultra
does, which its designers describe as dancing "between the worlds of sans and serifs,
fusing calligraphy and construction".

If the brand team ever supplies the real webfonts, the swap is two places: the
@font-face block and the --font-display token. Nothing else refers to the font by name.

Fraunces is licensed under the SIL Open Font License 1.1. Fraunces-OFL.txt is that
licence and must travel with the font files: the OFL requires the copyright notice and
licence to be distributed alongside the fonts. Do not delete it.

Note that data figures deliberately do NOT use this font. They read from --font-figure,
which stays on the neutral system face, because a display serif on "1,531,094" turns a
number you read into a number you decipher.


What belongs in git
===================

The brand marks are NOT committed: they are Lloyds' artwork, the top bar probes for them
and removes the chip cleanly when they are absent, so a clone without them still works.

The font files ARE meant to be committed, and this README with them. They are 226 KB of
woff2 between the two subsets, they are openly licensed, and unlike the marks they do not
degrade gracefully: a clone without them silently falls back to the system face and the
dashboard stops looking like the thing that was designed. The OFL also requires the
licence file to travel with them, which only works if it is in the repository.

    git add dashboard/assets/fraunces-latin.woff2 \
            dashboard/assets/fraunces-latin-ext.woff2 \
            dashboard/assets/Fraunces-OFL.txt \
            dashboard/assets/README.txt

Add them explicitly, by name. Never `git add .` in this repository: it holds multi-
hundred-megabyte CSVs that must not go near a commit.
