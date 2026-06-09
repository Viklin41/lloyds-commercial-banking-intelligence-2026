# Attrition signals from charges (sample)

Sample of 498 companies (SME, Midcorp, Large) that hold charges, across the Lloyds target sectors.

Rates below are measured against the companies that have at least one
recognised bank charge, because only those can show a bank being lost or
changed. Security agents, trustees, private equity funds, landlords, and
individuals are not counted as banks.

## Headline

| metric | value |
| --- | --- |
| companies probed | 498.0 |
| with any recognised bank charge | 383.0 |
| lost_all_banks (% of bank firms) | 32.6 |
| recent_bank_loss last 24m (% of bank firms) | 6.8 |
| reduced_banks (% of bank firms) | 53.8 |
| bank_switch (% of bank firms) | 12.5 |

## Lost all banks, split by distress

This is the important one. A firm in distress that has lost its bank is a
real attrition case. A healthy firm that lost its bank has most likely just
repaid its loan, which is a different story for the bank.

| is_distress | n | lost_all_banks_rate |
| --- | --- | --- |
| False | 375.0 | 32.5 |
| True | 8.0 | 37.5 |

## Lost all banks by size band

| size_band | n | lost_all_banks_rate |
| --- | --- | --- |
| Large | 123.0 | 39.8 |
| Midcorp | 146.0 | 30.1 |
| SME | 114.0 | 28.1 |

## Lost all banks by sector

| sector | n | lost_all_banks_rate |
| --- | --- | --- |
| Wholesale & retail | 114.0 | 32.5 |
| Manufacturing | 85.0 | 35.3 |
| Technology, legal & professional | 66.0 | 33.3 |
| Real estate | 50.0 | 26.0 |
| Healthcare | 31.0 | 22.6 |
| Fast growth & emerging | 18.0 | 50.0 |
| Agriculture | 11.0 | 18.2 |
| Public sector, education & charities | 8.0 | 62.5 |