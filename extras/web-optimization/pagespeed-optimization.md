You are a web performance optimization expert. I need you to analyze and optimize the PageSpeed Insights score for this page: [PAGE_URL]

## Phase 1: Audit

First, analyze the codebase and identify all performance issues. Check for:

1. **Critical request chains** — what JS/CSS blocks rendering? What's the chain depth and total latency?
2. **Unused JavaScript** — which bundles load eagerly but aren't needed on this page? (vendor libs, UI frameworks, animation libraries)
3. **Forced reflows** — any JS querying geometric properties (offsetWidth, getBoundingClientRect, getComputedStyle) during layout?
4. **Render-blocking resources** — external fonts, CSS, third-party scripts loading synchronously?
5. **LCP element** — what is it? Is it blocked behind JS execution? Is it preloaded?
6. **Image optimization** — are images in modern formats (WebP/AVIF)? Do they have width/height? Is lazy loading used for below-fold images?
7. **Third-party scripts** — analytics, tag managers, chat widgets loading before interaction?
8. **DOM size and complexity** — heavy component libraries used where plain HTML/CSS would work?
9. **Bundle splitting** — are routes lazy-loaded? Are heavy dependencies in shared chunks?

Present findings as a table:

| Issue | Impact (LCP/FCP/TBT/CLS) | Est. Savings | Effort |
|-------|--------------------------|-------------|--------|

## Phase 2: Implement fixes one by one

After sharing the report, wait for my approval. Then implement fixes ONE AT A TIME in this priority order:

1. **Inline static hero HTML** — add a static HTML shell of the above-fold content inside `<div id="root">` in index.html so it renders before React JS loads. React's createRoot will replace it on mount. Copy any hero images to `public/` for stable URLs. Add `<link rel="preload">` in `<head>` for the LCP image.

2. **Defer/remove unused JS from initial load** — lazy-load UI libraries (toasters, tooltips, modals) that aren't needed on first render. Remove components from shared/eager chunks if they're only used on specific routes. Replace heavy library components (Radix dropdowns, accordions) with plain CSS equivalents where possible.

3. **Remove forced reflows** — replace any offsetWidth/getBoundingClientRect reflow hacks with requestAnimationFrame or CSS-only alternatives. Simplify animation components (magnetic effects, ripple effects) to plain elements if the effect isn't essential.

4. **Defer third-party scripts** — load analytics/GTM via requestIdleCallback after window.load instead of eagerly. Remove any scaffolding scripts (e.g. gptengineer.js, lovable tags) from production.

5. **Optimize font loading** — self-host fonts or ensure `font-display: swap`. Preload the primary font file. Load font CSS with `media="print" onload="this.media='all'"` pattern.

6. **Optimize images** — ensure WebP/AVIF format, add explicit width/height, use `loading="lazy"` for below-fold, `fetchpriority="high"` for hero.

7. **Add `content-visibility: auto`** to below-fold sections to defer rendering work.

After each fix:
- Run `npm run build` to verify the build passes
- Show the before/after bundle size comparison
- Commit with a descriptive message
- Ask me before proceeding to the next fix

Do NOT implement multiple fixes at once. One commit per fix.

Replace `[PAGE_URL]` with the page you want to optimize.
