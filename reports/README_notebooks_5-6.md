# Task 6 explained simply: joining outside data to our company list

 Lloyds project:
linking unstructured and outside data onto the main Companies House dataset.

------------------------------------------------------------------------

## 1. The goal in one line
Take our big list of UK companies and attach useful outside signals to each one, so the bank can
spot which firms might need lending, support, or growth help.

## 2. Words and short forms (read this first)
- Companies House: the UK government register of all companies. Our base data comes from it.
- CSV: Comma Separated Values, a plain table file (like a spreadsheet saved as text).
- API: Application Programming Interface, a way for our code to ask a website for data directly.
- SME: Small and Medium sized Enterprise, a small company.
- BB: Business Banking. BCB: Business and Commercial Banking, the Lloyds team sponsoring us.
- Spine: our master list of companies, one row each, keyed on the company number.
- Crosswalk: a translation list that links a company to its other names and codes.
- Signals: a table of events about companies (winning a contract, posting a job, and so on).
- LEI: Legal Entity Identifier, a global id given to firms that trade or borrow money.
- Ticker: the short code a company has on the stock market (for example, a listed firm).
- DuckDB: a small database that lives in one file, no server needed. Like a smarter spreadsheet.
- RapidFuzz: a tool that scores how similar two pieces of text are (for matching names).
- Fuzzy matching: matching two names that are close but not identical (Acme Ltd vs Acme Limited).
- Postcode: the UK address code (for example W1J 5FJ). We use it to confirm a match is the right firm.
- GLEIF: the global organisation that runs the LEI register. Free to download.
- Wikidata: a free public database of facts, including some company ids.
- Contracts Finder: a free UK government website listing public sector contracts and who won them.
- OCDS: Open Contracting Data Standard, the data format Contracts Finder publishes in.
- Adzuna: a jobs website with a free data service (a future source, not built yet).
- Colab: Google Colaboratory, a free website that runs Python code in the cloud.
- Google Drive: Google's online file storage. We keep the data and results there.
- Branch: a separate copy of the project in version control where we do our work safely.
- gitignore: a list of files that should not be uploaded to the shared project (big or rebuildable).

## 3. The big idea
Different sources name companies differently (a number, an LEI, a ticker, or just a name), so we
need one backbone and a way to translate between them. We built a small knowledge graph (a set of
linked tables) in DuckDB with three tables:
1. companies: the spine, one row per company, keyed on the Companies House number.
2. identifiers: the crosswalk, linking each company to its other names and codes, with a note of
   where each link came from and how confident we are (1.0 means exact, lower means a guess).
3. signals: time stamped events about companies, again with a source and a confidence.

We also split companies into two groups in our heads:
- Tier A: all small firms, described by their Companies House behaviour and government data.
- Tier B: the few large or listed firms that also have news and market data.

## 4. What we built, step by step

### Notebook 5: build the spine and the crosswalk
1. Load the company list and clean it (one tidy company number per company).
2. Save it into a DuckDB file as the companies spine.
3. Fill the crosswalk with the safe, exact links first:
   - from Companies House itself: the number, the simplified name, and all previous names.
   - from Wikidata: LEI and ticker for any company that lists a Companies House number.
   - from GLEIF: the LEI for UK firms, matched by company number.
4. Create the empty signals table for the next notebook to fill.
5. Draw two charts and save the database.

### Notebook 6: add the first real signal (public contract wins)
1. Open the database and load the spine.
2. Download awarded public contracts from Contracts Finder.
3. For each contract supplier, find the matching company using a matching ladder:
   - first the company number if the notice gives one (most reliable),
   - then an exact name where the postcode also agrees,
   - then a close fuzzy name where the postcode also agrees,
   - and a weak unconfirmed match if there is no postcode to check.
4. Save the matches into the signals table as contract win events.
5. Draw four charts and save.

## 5. The results we got (full run)
- The full company list is 869,043 companies.
- Only 855 of them (0.10 percent) have an LEI, and none have a stock ticker. This is a key
  finding: small firms almost never appear in the big financial id systems, so we cannot rely on
  market data to understand them. We must use government and behaviour data instead.
- Over 130,000 companies have traded under a previous name at some point.
- From the public contracts we pulled, we matched 316 contract wins to 239 of our companies.
  Almost all of these (311 of 316) were confirmed by a company number or a postcode, so they are
  trustworthy. The biggest winners by value were real, well known firms (Deloitte, AECOM, and so
  on), which told us the matching was working.
- Honest caveat: contract wins lean towards larger firms, so for genuine small firm coverage the
  next source should be jobs data (Adzuna), which reaches smaller companies.

## 6. Problems we hit, and how we fixed them (the trial and error)
This is the messy real story, worth keeping.

1. Wrong coverage number (the orphan rows).
   - What happened: the crosswalk first reported that 9.14 percent of companies had an LEI. That
     looked too high.
   - Why: GLEIF and Wikidata return every UK company, and we were storing LEIs even for companies
     that are not in our list. Those extra rows inflated the count.
   - Fix: only store crosswalk rows for companies that are in our spine, and count coverage with
     a proper join. The real number is 0.10 percent.

2. The date crash (mixed time zones).
   - What happened: Notebook 6 crashed when turning contract dates into proper dates, with an
     error about the .dt accessor.
   - Why: Contracts Finder dates come with mixed time zones, so the column stayed as plain text.
   - Fix: add utc=True when converting, which lines all the dates up to one time zone.

3. The false matches (name collisions). This was the big one.
   - What happened: the first matching attempt gave silly results. A small AMAZON LTD in Oxford
     was credited with Amazon Web Services cloud contracts. A firm called & THE NEW ... LTD was
     given New Era Fuels Ltd's fuel contract. ACE TAX LTD was given taxi route contracts.
   - Why: matching only on the name. Big national suppliers share name fragments with unrelated
     small firms, and fuzzy matching latched onto them.
   - Fix: require the postcode to agree before accepting a name match. Different firms have
     different postcodes, so this throws out the wrong ones.

4. The empty postcode (zero matches).
   - What happened: after adding the postcode check, suddenly almost nothing matched, and it
     reported 0 suppliers with a postcode.
   - Why: Contracts Finder does not fill the proper postcode field for suppliers. The postcode is
     buried inside the street address text, for example "43 Berkeley Square W1J 5FJ".
   - Fix: read the postcode out of the address text using its recognisable UK shape. After this,
     94 percent of suppliers had a usable postcode and the matching worked properly.

5. Accidentally running the small sample.
   - What happened: twice we ran on 50,000 companies and got tiny match counts.
   - Why: the sample dial (SAMPLE_N) was left at its default of 50,000, and that sample is just
     the first slice of the alphabet, which is a biased corner of the data.
   - Fix: set SAMPLE_N to None to use all 869,043 companies. To make the full run fit in the free
     Colab memory, we also told it to read only the columns we need.

6. Files that should not be uploaded.
   - What happened: downloading the results folder dragged the big data file, the database, and
     the saved downloads into the project.
   - Why: these are large and can be rebuilt from the notebooks, so they should not be shared.
   - Fix: add them to the gitignore list (the database, the cache files, and stray copies of the
     data zip).

7. The download speed limit (rate limiting).
   - What happened: the contract download stops around page 25 with a 403 message.
   - Why: the website limits how fast we can ask, and asks us to wait five minutes.
   - For now: we take part of the year, and the download is saved so we can continue later.

## 7. How to run it (Google Colab with Drive)
1. Put the two notebooks and the data file (filtered_bb_sme_sectors.zip) in a Google Drive folder
   called Lloyds.
2. Open Notebook 5 with Colab, set SAMPLE_N to None for the full run, and choose Run all. It
   builds the database in the same Drive folder so it is kept.
3. Open Notebook 6 with Colab and choose Run all. It reads and updates the same database.
No passwords or keys are needed because the data sits in your own Drive.

## 8. What is next
- Add jobs data from Adzuna for better small firm coverage (needs a free key, which is quick).
- Optionally let the contract download wait and continue past the speed limit, for a full year.
- Optionally do one full LEI download for an exact coverage figure.
- Later, add the news data the team is preparing.
