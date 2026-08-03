# Source library: business, leadership & startup topics

This is a pick-and-choose reference, not something `newsdesk` auto-loads.
None of these topics live in `config.yaml`, which per `CONTRIBUTING.md` stays
a lean, curated starting point. If a topic below is useful to you, copy its
`sources:` block (and the include/boost/exclude keywords, adjusted to taste)
into your own `my.yaml`, then run `newsdesk -c my.yaml doctor` to confirm the
feeds are still alive before you build against them.

Every topic below will pick up `pattern_tiers` / `digest_patterns` from
`topic_defaults` once that feature ships (see
`docs/superpowers/specs/2026-08-03-multi-pattern-tabs-design.md`). There is no
per-topic `pattern:` / `digest_pattern:` key in these snippets on purpose;
add one later only if you want to override the default for a specific topic.

## Topic breakdown and how it maps to the 15 candidate areas

The task framing listed about 15 candidate areas. A few of those overlap
enough in practice (same writers, same publications, same keyword space)
that splitting them into separate topics would just mean duplicate sources
firing on duplicate stories. Here's the final set of 13 topics and how the
originals map onto it:

- **Startups & Founders** absorbs "entrepreneurship (solo / indie /
  bootstrapped)". Indie hacker and VC-backed founder content share enough
  writers (Arvid Kahl, Packy McCormick, YC) that a second topic would mostly
  duplicate this one.
- **Venture Capital & Startup Funding** stays separate from Startups &
  Founders: funding-and-market-signal content (term sheets, round sizes,
  fund strategy) reads differently from founder-operator content, and each
  has its own strong, distinct source pool.
- **Product Management** stands alone.
- **Leadership & Executive Coaching** merges "leadership & management" with
  "executive / enterprise coaching". In practice the coaches worth
  following (Lara Hogan, Michael Hyatt) write the same kind of material as
  the leadership writers (Seth Godin, Farnam Street) -- there wasn't enough
  distinct, high-quality coaching-specific content to justify a 14th topic.
- **Workplace Productivity & Efficiency** stands alone (individual and team
  effectiveness, distinct from HR policy or org structure).
- **Organizational Culture & Design** stands alone.
- **Remote & Hybrid Work** stands alone: distinct enough source pool
  (remote-first companies, remote job boards, remote-specific writers) to
  earn its own topic rather than folding into culture.
- **HR & People Ops** stands alone, kept distinct from Leadership since it's
  policy/practice-focused (HRIS, benefits, comp, hiring process) rather than
  individual leadership development.
- **Sales & Growth** stands alone.
- **Marketing Strategy** stands alone, kept distinct from Sales & Growth
  even though a couple of writers (Neil Patel) show up in both.
- **Innovation & New Business/Product Ideas** stands alone.
- **Board Governance & Company Strategy** stands alone.
- **Career Development / Professional Growth** stands alone.

That's 13 topics against roughly 15 candidates, with the two mergers
explained above.

## Summary table

| Topic | Slug | Verified sources |
| --- | --- | --- |
| Startups & Founders | `startups` | 8 |
| Venture Capital & Startup Funding | `venture-capital` | 8 |
| Product Management | `product-management` | 8 |
| Leadership & Executive Coaching | `leadership` | 8 |
| Workplace Productivity & Efficiency | `productivity` | 5 |
| Organizational Culture & Design | `org-culture` | 6 |
| Remote & Hybrid Work | `remote-work` | 5 |
| HR & People Ops | `hr-people-ops` | 6 |
| Sales & Growth | `sales-growth` | 6 |
| Marketing Strategy | `marketing` | 5 |
| Innovation & New Business Ideas | `innovation` | 5 |
| Board Governance & Company Strategy | `governance` | 5 |
| Career Development & Professional Growth | `career-growth` | 5 |

Total: 13 topics, 80 source entries across roughly 67 distinct feed URLs
(some sources, like Farnam Street or James Clear, genuinely earn a spot on
more than one topic's list, matching the style `config.yaml` already uses
for Schneier and Simon Willison across Security and Deep Reads).

All feeds below were verified with
`curl -sL -o /dev/null -w "%{http_code} %{content_type}"` plus a body check
for a real `<?xml`/`<rss`/`<feed` payload (not an HTML error page) on
2026-08-03. Feed URLs rot; re-run `newsdesk doctor` against anything you copy
out of here periodically, exactly as you would for `config.yaml` itself.

---

## Startups & Founders

**Suggested topic config:**
```yaml
- name: Startups & Founders
  slug: startups
  include: [startup, founder, founding, bootstrapped, indie hacker, solo founder,
            side project, MVP, product-market fit, pivot, cofounder, seed stage]
  boost: [YC, Y Combinator, solopreneur, first customer, launch, ramen profitable]
  exclude: [webinar, sponsored, "buyer's guide"]
  sources:
    - {url: "https://www.ycombinator.com/blog/rss", name: Y Combinator Blog, weight: 1.2}
    - {url: "https://blog.samaltman.com/posts.atom", name: Sam Altman, weight: 1.1}
    - {url: "https://world.hey.com/dhh/feed.atom", name: DHH, weight: 1.1}
    - {url: "https://thebootstrappedfounder.com/feed/", name: The Bootstrapped Founder, weight: 1.2}
    - {url: "https://www.notboring.co/feed", name: Not Boring, weight: 1.15}
    - {url: "https://stratechery.com/feed/", name: Stratechery, weight: 1.2}
    - {url: "https://foundr.com/feed", name: Foundr, weight: 0.95}
    - {url: "https://www.smartpassiveincome.com/feed/", name: Smart Passive Income, weight: 1.0}
```

Verified working as of 2026-08-03. Arvid Kahl's Bootstrapped Founder and Not
Boring are newsletter-native (Substack/ConvertKit-style) and carry genuine
editorial voice rather than SEO filler. Stratechery is subscriber-gated for
full posts but the RSS carries enough of each piece to be worth including
(`paywalled: true` is worth setting if you copy this in, since a chunk of
its value is behind a paid tier). Paul Graham's essays and Indie Hackers
were both tried and dropped: PG's site has no working RSS endpoint left
(`/rss.html` and `/rss.php` both 404 or serve a non-feed HTML wrapper), and
every Indie Hackers feed path tested returned the SPA's HTML shell instead
of XML.

## Venture Capital & Startup Funding

**Suggested topic config:**
```yaml
- name: Venture Capital & Startup Funding
  slug: venture-capital
  include: [venture capital, VC, funding round, Series A, Series B, seed round,
            term sheet, valuation, cap table, dilution, LP, fund, portfolio company]
  boost: [a16z, Sequoia, unicorn, down round, secondary, IPO]
  exclude: [sponsored, "buyer's guide"]
  sources:
    - {url: "https://avc.com/feed", name: "AVC (Fred Wilson)", weight: 1.25}
    - {url: "https://tomtunguz.com/index.xml", name: Tom Tunguz, weight: 1.2}
    - {url: "https://news.crunchbase.com/feed/", name: Crunchbase News, weight: 1.0}
    - {url: "https://www.saastr.com/feed/", name: SaaStr, weight: 1.1}
    - {url: "https://versionone.vc/feed/", name: VersionOne Ventures, weight: 1.1}
    - {url: "https://www.seedcamp.com/feed/", name: Seedcamp, weight: 1.0}
    - {url: "https://techcrunch.com/category/venture/feed/", name: "TechCrunch (Venture)", weight: 1.0}
    - {url: "https://www.axios.com/feeds/feed.rss?feedname=pro-rata", name: "Axios Pro Rata", weight: 1.15}
```

Verified working as of 2026-08-03. AVC and Tom Tunguz are individual-VC
blogs with 15+ years of a genuine, opinionated track record; SaaStr and
Crunchbase News are the closest things to trade-press-of-record for this
beat. Dropped: a16z (every `/feed`, `/feed/`, `/rss/`, `/newsletter/feed/`
path 404s, they appear to have no public feed anymore), CB Insights
(returns 403 to bare curl, likely bot-blocked), OpenView Partners (feed URL
serves the HTML site, not XML), and NFX/Point Nine/Bessemer Atlas (no
working feed found on any guessed path).

## Product Management

**Suggested topic config:**
```yaml
- name: Product Management
  slug: product-management
  include: [product management, roadmap, product-market fit, user research,
            discovery, prioritization, backlog, feature, product strategy,
            product sense, PM, product manager]
  boost: [Cagan, opportunity solution tree, jobs to be done, north star metric]
  exclude: [sponsored, webinar]
  sources:
    - {url: "https://www.lennysnewsletter.com/feed", name: "Lenny's Newsletter", weight: 1.3}
    - {url: "https://productcoalition.com/feed", name: Product Coalition, weight: 1.0}
    - {url: "https://www.svpg.com/feed/", name: "SVPG (Marty Cagan)", weight: 1.25}
    - {url: "https://www.producttalk.org/feed/", name: "Product Talk (Teresa Torres)", weight: 1.2}
    - {url: "https://cutlefish.substack.com/feed", name: "Cutlefish (John Cutler)", weight: 1.2}
    - {url: "https://blackboxofpm.substack.com/feed", name: Black Box of PM, weight: 1.05}
    - {url: "https://www.aakashg.com/feed", name: Aakash Gupta, weight: 1.05}
    - {url: "https://www.intercom.com/blog/feed/", name: Intercom Blog, weight: 1.0}
```

Verified working as of 2026-08-03. Lenny's Newsletter, SVPG and Product
Talk are the three most-cited individual voices in this space and all have
live, clean RSS. Mind the Product's site now serves its "feed" as JSON, not
RSS/Atom, so it's excluded despite being a well-known publication; if they
restore an XML feed it's worth re-adding.

## Leadership & Executive Coaching

**Suggested topic config:**
```yaml
- name: Leadership & Executive Coaching
  slug: leadership
  include: [leadership, executive, management, coaching, feedback, delegation,
            decision-making, org design, one-on-one, performance review,
            executive coach, C-suite, succession]
  boost: [psychological safety, servant leadership, radical candor, staff meeting]
  exclude: [sponsored, webinar]
  sources:
    - {url: "https://seths.blog/feed/", name: Seth Godin, weight: 1.15}
    - {url: "https://fs.blog/feed/", name: Farnam Street, weight: 1.2}
    - {url: "https://michaelhyatt.com/feed", name: Michael Hyatt, weight: 1.1}
    - {url: "https://larahogan.me/feed.xml", name: Lara Hogan, weight: 1.15}
    - {url: "http://feeds.harvardbusiness.org/harvardbusiness", name: "Harvard Business Review", weight: 1.1}
    - {url: "https://www.fastcompany.com/section/leadership/rss", name: "Fast Company (Leadership)", weight: 1.0}
    - {url: "https://www.forbes.com/sites/johnkotter/feed/", name: "Forbes / John Kotter", weight: 1.1}
    - {url: "https://www.metisstrategy.com/feed/", name: Metis Strategy, weight: 1.0}
```

Verified working as of 2026-08-03. Note the HBR feed URL: the modern
`hbr.org/rss` and per-topic `hbr.org/topic/.../rss` paths all 404 or serve
HTML; the working feed is still on the legacy `feeds.harvardbusiness.org`
host over plain HTTP, oddly enough, and it's a single firehose across all
of HBR rather than a leadership-only feed, so expect noise. Lara Hogan's
site moved its feed to `/feed.xml`; the more obvious `/feed/` and
`/blog/index.xml` guesses both 404.

## Workplace Productivity & Efficiency

**Suggested topic config:**
```yaml
- name: Workplace Productivity & Efficiency
  slug: productivity
  include: [productivity, focus, deep work, time management, meeting, calendar,
            async, workflow, habit, procrastination, attention, burnout]
  boost: [deep work, time blocking, single-tasking, notification]
  exclude: [sponsored, "app roundup"]
  sources:
    - {url: "https://www.calnewport.com/blog/feed/", name: Cal Newport, weight: 1.25}
    - {url: "https://jamesclear.com/feed", name: James Clear, weight: 1.15}
    - {url: "https://www.nirandfar.com/feed/", name: "Nir Eyal", weight: 1.1}
    - {url: "https://zapier.com/blog/feed/", name: Zapier Blog, weight: 1.0}
    - {url: "https://buffer.com/resources/rss", name: Buffer Resources, weight: 1.0}
```

Verified working as of 2026-08-03. This is a thinner list than the others:
a lot of the obvious "productivity blog" candidates (Asana's inspiration
blog, Doist's blog) either have no public feed or serve their feed URL as
an HTML page now. Five solid, individual-voice sources beat padding this
out with SEO content-farm productivity sites.

## Organizational Culture & Design

**Suggested topic config:**
```yaml
- name: Organizational Culture & Design
  slug: org-culture
  include: [organizational culture, org design, org structure, values, rituals,
            onboarding, team topology, span of control, reorg, culture fit]
  boost: [psychological safety, flat structure, matrix org, team of teams]
  exclude: [sponsored, webinar]
  sources:
    - {url: "https://www.fastcompany.com/co-design/rss", name: "Fast Company Co.Design", weight: 1.0}
    - {url: "https://www.fastcompany.com/section/work-life/rss", name: "Fast Company Work Life", weight: 1.05}
    - {url: "https://sloanreview.mit.edu/topic/leading-change/feed/", name: "MIT Sloan (Leading Change)", weight: 1.15}
    - {url: "https://knowledge.wharton.upenn.edu/feed/", name: "Knowledge@Wharton", weight: 1.1}
    - {url: "https://www.betterup.com/blog/rss.xml", name: BetterUp Blog, weight: 1.0}
    - {url: "http://feeds.harvardbusiness.org/harvardbusiness", name: "Harvard Business Review", weight: 1.0}
```

Verified working as of 2026-08-03. Culture-specific publications had the
worst hit rate of any topic here: CultureAmp, Great Place To Work, The
Ready, TinyPulse and re:Work all either 404 on every guessed feed path or
now gate their blog behind Cloudflare in a way that blocks a bare curl.
MIT Sloan's "Leading Change" topic feed and the two Fast Company section
feeds are the strongest genuinely-on-topic sources that actually work.

## Remote & Hybrid Work

**Suggested topic config:**
```yaml
- name: Remote & Hybrid Work
  slug: remote-work
  include: [remote work, hybrid work, distributed team, async, work from home,
            return to office, RTO, time zone, remote-first, coworking]
  boost: [4-day workweek, digital nomad, remote hiring]
  exclude: [sponsored, "job board spam"]
  sources:
    - {url: "https://hackernoon.com/tagged/remote-work/feed", name: "HackerNoon (Remote Work)", weight: 1.0}
    - {url: "https://distantjob.com/blog/feed/", name: DistantJob Blog, weight: 1.05}
    - {url: "https://about.gitlab.com/atom.xml", name: GitLab Blog, weight: 1.2}
    - {url: "https://weworkremotely.com/remote-jobs.rss", name: We Work Remotely, weight: 0.9}
    - {url: "https://buffer.com/resources/rss", name: Buffer Resources, weight: 1.0}
```

Verified working as of 2026-08-03. GitLab is the highest-weighted source
here on purpose: they've run fully remote at scale for a decade and their
blog is genuine first-party operating experience, not marketing copy. We
Work Remotely's feed is actually their jobs listing, not editorial content,
included at a lower weight as a labor-market signal rather than for prose.
Several remote-work-specific outlets (Remote.co, Reworked, Owl Labs) had no
working feed on any path tried.

## HR & People Ops

**Suggested topic config:**
```yaml
- name: HR & People Ops
  slug: hr-people-ops
  include: [HR, people ops, human resources, hiring, onboarding, compensation,
            benefits, performance management, employee experience, attrition,
            headcount, HRIS]
  boost: [pay transparency, total rewards, people analytics]
  exclude: [sponsored, "job board spam"]
  sources:
    - {url: "https://joshbersin.com/feed/", name: Josh Bersin, weight: 1.25}
    - {url: "https://www.hrdive.com/feeds/news/", name: HR Dive, weight: 1.1}
    - {url: "https://hrexecutive.com/feed/", name: HR Executive, weight: 1.05}
    - {url: "https://www.predictiveindex.com/blog/feed/", name: Predictive Index Blog, weight: 1.0}
    - {url: "https://www.glassdoor.com/blog/feed/", name: Glassdoor Blog, weight: 0.95}
    - {url: "https://www.betterup.com/blog/rss.xml", name: BetterUp Blog, weight: 1.0}
```

Verified working as of 2026-08-03. Josh Bersin is the closest thing to an
industry-analyst-of-record for HR tech and practice, and his feed carries
full posts. SHRM, TLNT and eremedia all 404 on their expected feed paths.

## Sales & Growth

**Suggested topic config:**
```yaml
- name: Sales & Growth
  slug: sales-growth
  include: [sales, growth, pipeline, quota, cold outreach, conversion,
            churn, retention, funnel, growth loop, activation, CAC, LTV]
  boost: [PLG, product-led growth, sales enablement, outbound]
  exclude: [sponsored, "buyer's guide"]
  sources:
    - {url: "https://blog.close.com/rss.xml", name: "Close CRM Blog", weight: 1.15}
    - {url: "https://blog.hubspot.com/sales/rss.xml", name: "HubSpot Sales Blog", weight: 1.0}
    - {url: "https://www.salesforce.com/blog/feed/", name: Salesforce Blog, weight: 0.95}
    - {url: "https://www.growthhackers.com/feed", name: GrowthHackers, weight: 1.05}
    - {url: "https://andrewchen.com/feed/", name: Andrew Chen, weight: 1.2}
    - {url: "https://neilpatel.com/feed/", name: Neil Patel, weight: 1.0}
```

Verified working as of 2026-08-03. Andrew Chen's is the strongest
individual-voice source in this list (a16z growth partner, long track
record on network effects and growth loops specifically). Close's blog
skews toward SMB/founder-led sales rather than enterprise, worth knowing
if you're tuning `include`/`exclude` for a specific sales motion.

## Marketing Strategy

**Suggested topic config:**
```yaml
- name: Marketing Strategy
  slug: marketing
  include: [marketing, brand, positioning, content marketing, SEO, campaign,
            copywriting, audience, messaging, go-to-market, GTM]
  boost: [brand voice, storytelling, distribution channel]
  exclude: [sponsored, "listicle"]
  sources:
    - {url: "https://blog.hubspot.com/marketing/rss.xml", name: "HubSpot Marketing Blog", weight: 1.0}
    - {url: "https://neilpatel.com/feed/", name: Neil Patel, weight: 1.0}
    - {url: "https://www.copyblogger.com/feed/", name: Copyblogger, weight: 1.05}
    - {url: "https://seths.blog/feed/", name: Seth Godin, weight: 1.1}
    - {url: "https://www.chiefoutsiders.com/blog/rss.xml", name: Chief Outsiders, weight: 0.95}
```

Verified working as of 2026-08-03. This is the topic where the "SEO
content farm" risk is highest; Copyblogger and Seth Godin are included
specifically because they have genuine, decades-long editorial identity
rather than programmatic content. Content Marketing Institute and
MarketingProfs were tried and dropped: CMI's feed URL now serves the HTML
site, and MarketingProfs' feed paths are Cloudflare-gated (403 to curl).

## Innovation & New Business Ideas

**Suggested topic config:**
```yaml
- name: Innovation & New Business Ideas
  slug: innovation
  include: [innovation, disruption, new business model, emerging technology,
            R&D, ideation, business model, market opportunity, whitespace]
  boost: [S-curve, blue ocean, first mover, category creation]
  exclude: [sponsored, "listicle"]
  sources:
    - {url: "https://www.technologyreview.com/feed/", name: "MIT Technology Review", weight: 1.1}
    - {url: "https://sloanreview.mit.edu/topic/strategy/feed/", name: "MIT Sloan (Strategy)", weight: 1.15}
    - {url: "https://www.notboring.co/feed", name: Not Boring, weight: 1.1}
    - {url: "https://stratechery.com/feed/", name: Stratechery, weight: 1.15}
    - {url: "https://knowledge.wharton.upenn.edu/feed/", name: "Knowledge@Wharton", weight: 1.0}
```

Verified working as of 2026-08-03. Innovation Excellence, a once-prominent
publication in this space, now serves a private/parked page on its feed
path and was dropped. Stratechery again is worth a `paywalled: true` note
if you copy this in.

## Board Governance & Company Strategy

**Suggested topic config:**
```yaml
- name: Board Governance & Company Strategy
  slug: governance
  include: [board of directors, governance, fiduciary, proxy, shareholder,
            company strategy, strategic planning, M&A, activist investor,
            board seat, audit committee]
  boost: [ESG, say-on-pay, board composition]
  exclude: [sponsored]
  sources:
    - {url: "https://corpgov.law.harvard.edu/feed/", name: "Harvard Law Forum on Corporate Governance", weight: 1.3}
    - {url: "https://boardsource.org/feed/", name: BoardSource, weight: 1.1}
    - {url: "https://hbswk.hbs.edu/rss/all.rss", name: "HBS Working Knowledge", weight: 1.15}
    - {url: "https://www.mckinsey.com/insights/rss", name: "McKinsey Insights", weight: 1.1}
    - {url: "https://www.metisstrategy.com/feed/", name: Metis Strategy, weight: 1.0}
```

Verified working as of 2026-08-03. The Harvard Law Forum is the most
authoritative source on the list by a wide margin (it's where actual
governance scholarship and practitioner commentary gets published first).
HBS Working Knowledge's feed is Atom rather than RSS, which is fine, same
as `martinfowler.com/feed.atom` in `config.yaml`.

## Career Development & Professional Growth

**Suggested topic config:**
```yaml
- name: Career Development & Professional Growth
  slug: career-growth
  include: [career, promotion, job search, resume, interview, mentorship,
            professional development, skill, networking, career change]
  boost: [imposter syndrome, negotiation, career ladder]
  exclude: [sponsored, "job board spam"]
  sources:
    - {url: "https://www.askamanager.org/feed", name: "Ask a Manager", weight: 1.3}
    - {url: "https://80000hours.org/feed/", name: "80,000 Hours", weight: 1.1}
    - {url: "https://jamesclear.com/feed", name: James Clear, weight: 1.1}
    - {url: "https://www.workingnation.com/feed/", name: WorkingNation, weight: 1.0}
    - {url: "https://fs.blog/feed/", name: Farnam Street, weight: 1.1}
```

Verified working as of 2026-08-03. Ask a Manager is the standout: 15+
years of a genuinely singular editorial voice on workplace and career
questions. This was the hardest topic to fill: The Muse, Career Contessa,
The Balance Careers, LiveCareer and TheLadders all either 404, return
Cloudflare 403s, or (in The Muse's case) intermittently 503 across every
feed path tried.

---

## Outstanding

All 13 topics above are complete with fully verified sources. Nothing was
left half-done or padded with unverified URLs to hit a target count; where
a topic's list is on the shorter end (Productivity and Remote & Hybrid Work
at 5 sources each), that reflects a genuinely thinner pool of live, quality
feeds after testing 15-20+ candidate URLs each, not a shortcut.
