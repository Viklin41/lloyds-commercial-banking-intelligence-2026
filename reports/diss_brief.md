## **Identifying Customer needs via Companies House & Unstructured Data** 

## **Context** 

Commercial Banking serves small and medium businesses as well as corporate and institutional clients. The Commercial Banking Division at Lloyds Banking Group provides lending, transactional banking, working capital management, debt financing and risk management services. Through investment in digital capability and product development, Commercial Banking delivers an enhanced customer experience with a digital-first business model and expanded client propositions. 

## **Problem Statement** 

We want to explore whether publicly available data can help identify potential business opportunities or risks for clients and potential clients. Specifically, the goal is to link structured company data from Companies House with unstructured media data (e.g., news articles, global event databases) to detect patterns in external behaviour and news coverage. These patterns could indicate a company’s future needs, such as lending, business support, or growth opportunities, and help the bank proactively engage with clients or prospects who are not currently banking with Lloyds. 

In short: 

**Can external public data (company filings + media coverage) be used to predict business needs and inform commercial banking strategies?** 

## **Key Information Sources (Suggested)** 

## **1. Companies House** 

## **What it is:** 

Companies House is the UK’s official registrar of companies. It provides structured data on all registered businesses, including: 

- Company name, registration number, and address 

- Filing history (annual accounts, confirmation statements) 

- Directors and officers 

- SIC codes (industry classification) 

- Financial information (balance sheets, profit/loss) 

## **How it could be used:** 

- Company profiling: Identify industry, size, and financial health. 

- Trend analysis: Detect changes in filings (e.g., late filings, director changes) as potential risk signals. 

- Linkage: Use company name or registration number to connect with media coverage. 

## **How to access:** 

- API: Companies House API (RESTful, free with registration). 

- Bulk data: Downloadable datasets for research purposes. 

- Formats: JSON, CSV. 

## **2. GDELT (Global Database of Events, Language, and Tone)** 

## **What it is:** 

GDELT is a global news and event monitoring platform that tracks media coverage in over 100 languages. It provides: 

- Event data (political, economic, social) 

- Sentiment analysis 

- Geographic tagging 

- Real-time updates 

## **How it could be used:** 

- Sentiment tracking: Monitor positive/negative news about companies. 

- Event correlation: Identify external shocks (e.g., supply chain disruptions, protests) that might affect business needs. 

- Trend detection: Volume of coverage as a proxy for company visibility or stress. 

## **How to access:** 

- API: GDELT API (free, supports queries by keyword, date range). 

- Data format: CSV, JSON. 

- Tools: Can integrate with Python for NLP and time-series analysis 

## **3. NewsAPI** 

## **What it is:** 

NewsAPI aggregates news articles from thousands of sources worldwide. It provides: 

- Headlines and full-text articles 

- Metadata (source, author, publication date) 

- Keyword-based search 

## **How it could be used:** 

- Company-specific monitoring: Pull recent articles mentioning a company. 

- Topic modelling: Identify themes in coverage (e.g., expansion, funding). 

- Sentiment analysis: Gauge tone of coverage for risk/opportunity signals. 

## **How to access:** 

- API: NewsAPI (requires API key; free tier available). 

- Query options: Filter by keyword, date, language, source. 

- Formats: JSON. 

## **4. OpenCorporates** 

## **What it is:** 

OpenCorporates is a global database of company information, like Companies House but covering multiple jurisdictions. 

## **How it could be used:** 

- Cross-border analysis: Identify international subsidiaries or parent companies. 

- Prospect identification: Spot non-banked companies operating in the UK but registered abroad. 

## **How to access:** 

- API: OpenCorporates API (free tier available). 

- Bulk data: Available for research. 

- Formats: JSON. 

## **5. Financial News & Market Data APIs** 

## **Examples: Yahoo Finance API, Alpha Vantage** 

## **What it is:** 

APIs providing financial market data, stock prices, and company fundamentals. 

## **How it could be used:** 

- Market sentiment: Correlate stock performance with media coverage. 

- Financial health indicators: Use ratios and trends for predictive modelling. 

## **How to access:** 

- Yahoo Finance: Free Python libraries (e.g., yfinance). 

- Alpha Vantage: Requires API key (free tier available). 

**Expected Deliverables** 

- A clear methodology for linking Companies House and media data. 

- 

   - Exploratory analysis showing trends and correlations. 

- A prototype model (even if limited by data availability), for example to predict financing need or future company growth. 

- 

- A discussion of business implications, limitations, and suggested next steps. 

