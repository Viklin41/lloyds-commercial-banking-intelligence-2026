Brand assets for the dashboard
==============================

Drop the official Lloyds mark in this folder as one of:

    lloyds-logo.svg      (preferred, scales cleanly)
    lloyds-logo.png      (fallback, use a transparent background)

The top bar looks for the .svg first, then the .png. If neither is present it
falls back to the placeholder horse silhouette drawn inline in index.html.

The mark sits inside a white rounded chip, because the official horse is black
and the top bar is dark green. That keeps the asset unmodified, which is what
brand guidelines normally require. Do not recolour the supplied file.

Nothing in this folder is committed to git.
