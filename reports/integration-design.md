# Joining everyone's work into one dashboard

Nothing here is final. It is a starting point so we can agree quickly and then split the work.

---

## 1. The goal in one line

Someone types a company name into a box, and the screen shows everything the whole team has
ever found out about that company, from every pipeline we have built.

## 2. Words used below

- **Spine**: our master list of companies, one row per company, keyed on the company number.
  Sam already built one.
- **Signal**: one fact about one company on one date. "Won a contract on 3 March." "Had a
  winding-up petition on 9 May." "Appeared in a news story on 1 June."
- **Signals table**: one big table where every signal from every source lives, in the same shape.
- **Adapter**: a small piece of code that takes the output your notebook already produces and
  turns it into rows for the signals table. It does not change your notebook.
- **Store**: the finished database file the dashboard reads from.

## 3. The problem right now

We have eight branches and roughly twenty notebooks. Each one produces a different shape of
output, saved in a different place, with a different idea of what a company key looks like.

Nobody can answer "what do we know about company 12345678" without opening six notebooks.

That is the only problem we are solving. We are **not** rebuilding anyone's pipeline.

## 4. idea

Every pipeline keeps working exactly as it does today. We add one thin translation step after
each one, and everything lands in a single table.

```
your notebook  ->  adapter  ->  signals table  ->  dashboard
(unchanged)       (~30 lines)   (one shared      (reads only,
                                 shape)           never fetches)
```

The dashboard never calls an API and never opens a CSV. It only reads the store. That keeps it
fast, keeps it working offline in a demo, and means an examiner can re-run it and get the same
answer.

## 5. what has been built?

notebook `05_spine_crosswalk.ipynb` (non dramatic) already created three tables we need:

- `companies`: the spine, one row per company.
- `identifiers`: the crosswalk, linking a company to its other names and codes, with a note of
  where each link came from and how confident we are.
- `signals`: the events table, already with the right columns, and already commented with
  `news | hiring | contract_win | grant | filing | ...` as the intended types.

**Proposal: we adopt Sam's schema as-is and build on it, rather than inventing a new one.**
That is the single biggest shortcut available to us.

## 6. The one thing we must agree on

Every adapter, from every source, must produce rows in this exact shape:

| column | meaning | example |
|---|---|---|
| `company_number` | the spine key, always | `12345678` |
| `signal_type` | which kind of signal | `gazette_petition` |
| `signal_date` | the date the thing happened | `2026-05-09` |
| `value` | a number, if there is one | `1` |
| `detail` | free text to show on screen | `"Petition to wind up"` |
| `source` | which pipeline produced it | `gazette` |
| `confidence` | 1.0 exact match, lower if fuzzy | `1.0` |
| `retrieved_at` | when we pulled it | `2026-06-30` |

This is already Sam's table definition. We are just agreeing to stick to it.

Three rules that go with it, which matter more than they look:

1. **Always join on the company number, never on the company name.**
2. **Every signal must have a real date.** No nulls. If we lose the date, we cannot show a
   timeline and we can accidentally leak the future into Viktor's model.
3. **A company with no signals is a real answer, not a missing one.** Most UK small companies
   have no news and no notices. The dashboard should say so plainly rather than show a blank.

## 7. Who does what

The suggestion is to split by **type of source**, which is what Viktor asked for. Roughly:
Sam takes the government and money sources, Vishal takes the text and media sources.

### Sam's part

**Sources you would own:**

- Contracts Finder (public contract wins) - notebook 06, already built
- Adzuna (job adverts, a hiring signal) - notebook 07, already built
- Land Registry (property) - notebook 08, already built
- IPO and trade marks - notebook 09, already built
- The spine and the crosswalk - notebook 05, already built

Jobs: 

- **Identity resolution.** Turning whatever the user types into the right company number,
  including the fuzzy name plus postcode matching you already wrote. This is the front door of
  the whole dashboard, and you are the only person who has built it.
- **Four adapters**, one per source above, turning your existing outputs into signal rows.
- **The company profile half of the screen**: the header, the size and sector, the metric tiles.

**What you would not have to do:** nothing gets rewritten. Your notebooks stay as they are.

### Vishal's part

- Sources: the Gazette (insolvency and distress notices), news and sentiment (Guardian, NewsAPI,
  GDELT findings).
- Jobs: keeping the signal shape honest across sources, the source registry, and the evidence
  half of the screen (the timeline, the notices, the articles, and where each fact came from).

### Viktor and Sneha

They stay where they are. Their SHAP work reads from our store and gives back model scores per
company, which the dashboard shows in one panel. They are not part of the integration work.

## 8. The open question for the three of us

**Which company list is the master list?** There are currently three, and they disagree:

- Sam's spine: 869,043 companies
- The SHAP feature matrix: 1,372,321 companies
- The 33-month panel: 2,038,130 companies

A company can be in one and missing from another, so until we pick one, every join quietly
drops rows and nobody notices. **This is the first thing to settle in our meeting**, before any
code. Sam, you built the 869k spine, so you are best placed to say why it differs and whether
it can be rebuilt on the wider list.

## 9. Things we already know (bad)

Worth reading once so nobody is surprised later.

- **Company numbers are formatted differently in different places.** Some code keeps them
  exactly as they came, some pads them to 8 digits. Some CSV column names have a leading space.
  We need one shared cleaning function that everybody calls.
- **Contracts Finder has been built three times**, by Sam, by Sneha, and again in the SHAP
  branch. We should pick one and archive the other two.
- **Sentiment has been done two different ways**, VADER and TextBlob on one side, FinBERT on the
  other. We need to pick one, or record which method was used per row.
- **Matches are not always certain.** Name plus postcode matching is about 92% correct, and only
  55% of Gazette notices carry a company number at all. The confidence value must survive all
  the way to the screen, so a shaky match never looks like a certain one.
- **Some outputs were never saved.** At least one notebook produced results only in memory. If
  it is not on disk, it cannot be integrated.
- **The data files are not in git.** We will need one shared database file, or a script that
  rebuilds it, or nobody else can run the dashboard.

## 10. What the dashboard shows

One search box. Then one page per company:

- Name, number, status, age, sector, size, address.
- A row of tiles, one per source, each showing what we have, including an honest "nothing found".
- **One timeline with every signal from every source on it.** This is the view no single branch
  can produce today, and it is the thing that will sell the project.
- A panel per source: Gazette notices, news with sentiment, contracts, hiring, property, trade
  marks, lenders and charges.
- The model scores from Viktor and Sneha, labelled as signal indices rather than predictions.
- For every fact on screen: which source, which date, how confident.

## 11. Suggested order of work

1. Agree the signal shape in section 6, and pick the master list in section 8. (One meeting.)
2. Build the empty store, on Sam's schema.
3. Each of us writes **one** adapter, end to end, into the store. Just one each.
4. Look at the result together. If the shape is wrong, we find out now, cheaply.
5. Only then write the remaining adapters, and only then start the screen.

Step 3 is deliberately small. Two adapters is enough to prove the design works, and cheap enough
to throw away if it does not.

## 12. What we are deliberately not doing

- Not rebuilding anyone's pipeline.
- Not having the dashboard call APIs live. Everything is precomputed into the store first.
  (We can add a "refresh this company" button later for the free sources, if there is time.)
- Not merging all the branches into one. Each source stays in its own notebook.
