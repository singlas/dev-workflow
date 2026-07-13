You are an SEO, GEO, and AEO optimization expert. Perform a complete audit of this website's codebase and implement all improvements.

Replace `[SITE_URL]` with the target site. Replace `[BUSINESS_NAME]`, `[BUSINESS_TYPE]`, and other bracketed placeholders with actual values from the codebase.

## Phase 1: Audit

Scan every HTML file, template, layout, and config in the codebase. For each category below, report what exists, what's missing, and what's broken.

Present findings as a table:

| Category | Issue | Current State | Required Fix | Priority |
|----------|-------|---------------|-------------|----------|

### 1. Technical SEO

- **Meta tags** — title (under 60 chars, primary keyword + brand), description (under 160 chars, include CTA), viewport, charset
- **Canonical URL** — `rel="canonical"` on every page to prevent duplicate content
- **Open Graph** — `og:title`, `og:description`, `og:image` (1200x630, descriptive alt), `og:locale`, `og:type`, `og:url`, `og:site_name`
- **Twitter Cards** — `twitter:card` (summary_large_image), `twitter:title`, `twitter:description`, `twitter:image`
- **Heading hierarchy** — single `<h1>` per page, logical `<h2>`-`<h6>` nesting, no skipped levels
- **Semantic HTML** — `<main>`, `<article>`, `<section>`, `<nav>`, `<header>`, `<footer>` instead of generic `<div>`s
- **Image optimization** — WebP/AVIF format, descriptive keyword-rich `alt` text, explicit `width`/`height` to prevent CLS, `loading="lazy"` for below-fold, `fetchpriority="high"` for hero/LCP image
- **Internal linking** — descriptive anchor text (not "click here"), breadcrumb navigation where appropriate
- **Performance** — lazy load below-fold images, preload LCP image, remove unused CSS/JS, `content-visibility: auto` on below-fold sections

### 2. Crawl & Indexing

- **sitemap.xml** — exists, includes all public pages, correct `<priority>`, `<changefreq>`, `<lastmod>` values
- **robots.txt** — proper crawl directives, references sitemap URL, blocks admin/API/auth routes
- **Web app manifest** — `manifest.json` with `name`, `short_name`, `icons` (192x192 + 512x512), `theme_color`, `background_color`, `display`

### 3. Structured Data (JSON-LD)

Check for and implement all relevant schemas:

- **Organization** or **LocalBusiness** — name, url, logo, description, contactPoint, sameAs (social profiles)
- **WebSite** — with SearchAction if the site has search functionality
- **BreadcrumbList** — on all pages with navigation depth
- **FAQPage** — Question + AcceptedAnswer pairs matching visible FAQ content
- **Person** — for founders/team pages (with `alumniOf`, `jobTitle`, `knowsAbout` for E-E-A-T signals)
- **Other relevant types** — Product, Service, Course, Event, Review, HowTo, Article

For location-based businesses, add to LocalBusiness:
- `address` (PostalAddress), `geo` (lat/lng), `telephone`, `openingHoursSpecification`, `areaServed`, `priceRange`
- Geo meta tags: `geo.region`, `geo.placename`, `geo.position`, `ICBM`
- NAP consistency: verify Name, Address, Phone are identical everywhere on the site
- Google Maps embed or link where the address appears

### 4. GEO (Generative Engine Optimization)

Optimize for AI search engines (ChatGPT, Perplexity, Gemini, Claude):

- **llms.txt** — create at site root. Concise, well-structured summary: who, what, where, unique value prop, contact, key links. Include pointer to `llms-full.txt`
- **llms-full.txt** — comprehensive version: about, methodology, full team bios, all offerings with descriptions, complete FAQ, testimonials, contact details
- **HTML discoverability** — add `<link rel="alternate" type="text/plain" href="/llms.txt" title="LLM Summary">` in `<head>`
- **Content structure** — use clear factual claims, specific numbers, and authoritative statements that AI can extract and cite
- **E-E-A-T signals** — surface founder credentials, years of experience, number of customers served, certifications, affiliations, media mentions

### 5. AEO (Answer Engine Optimization)

Optimize for voice search, featured snippets, and AI answer boxes:

- **FAQ section** — visible on-page FAQ using `<details>`/`<summary>` for collapsible answers
- **FAQ schema** — FAQPage JSON-LD that mirrors the visible FAQ content exactly
- **Question format** — natural-language questions people actually ask ("How much does X cost?" not "Pricing information")
- **Answer format** — concise, direct first sentence (the snippet target), then supporting detail
- **Semantic FAQ markup** — use `<dl>`/`<dt>`/`<dd>` or `<details>`/`<summary>` — not styled `<div>`s
- **HowTo schema** — for any step-by-step content on the site

### 6. Security & Standards

- **security.txt** — create at `/.well-known/security.txt` with `Contact`, `Preferred-Languages`, `Canonical`
- **humans.txt** — optional, credit the team

## Phase 2: Implement fixes one by one

After sharing the audit report, wait for my approval. Then implement fixes ONE AT A TIME in this priority order:

1. **Meta tags + canonical URLs** — title, description, canonical on every page
2. **Structured data (JSON-LD)** — Organization/LocalBusiness, FAQPage, BreadcrumbList, Person
3. **Open Graph + Twitter Cards** — complete social sharing metadata
4. **Semantic HTML cleanup** — replace generic divs with semantic elements, fix heading hierarchy
5. **Sitemap + robots.txt** — create or fix crawl/index configuration
6. **Image optimization** — WebP conversion, alt text, width/height, lazy loading
7. **llms.txt + llms-full.txt** — create GEO files for AI search engines
8. **FAQ section + AEO markup** — visible FAQ with schema and semantic HTML
9. **security.txt + manifest.json** — standards compliance files
10. **Geo meta tags + local SEO** — if location-based business

After each fix:
- Explain the SEO/GEO/AEO rationale in one line
- Run the build to verify it passes
- Verify content consistency across page, JSON-LD, llms.txt, and FAQ
- Commit with a descriptive message
- Ask me before proceeding to the next fix

Do NOT implement multiple fixes at once. One commit per fix.

## Validation checklist

After all fixes are implemented, verify:

- [ ] Every page has unique title + description
- [ ] JSON-LD validates at schema.org/validator or Google Rich Results Test
- [ ] `sitemap.xml` is accessible and lists all public pages
- [ ] `robots.txt` references sitemap and doesn't block important pages
- [ ] `llms.txt` is accessible at site root
- [ ] Open Graph preview looks correct (use opengraph.xyz or similar)
- [ ] No keyword stuffing — content reads naturally for humans
- [ ] Build passes with zero errors
