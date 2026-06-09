# Attrition labels from filing history (sample)

Sample of 600 companies, balanced across outcome classes (healthy, distress, dormant), all holding charges.

A distress event is the first strike-off notice, insolvency filing, or
dormant accounts filing found in a company's filing history.

## Event rate and bank loss by outcome class

| status_class | n | event_rate | lost_all_banks_rate |
| --- | --- | --- | --- |
| distress | 200.0 | 99.5 | 28.0 |
| dormant | 200.0 | 100.0 | 27.0 |
| healthy | 200.0 | 9.0 | 17.5 |

## Does losing the bank go with distress?

Share of firms that have lost all their banks, split by whether the firm
had a distress event. If the event group is higher, bank loss is
associated with attrition.

| group | n | lost_all_banks_rate |
| --- | --- | --- |
| had_distress_event | 417.0 | 26.9 |
| no_event | 183.0 | 18.0 |

## Lead-lag: did the bank loss come first?

Among firms that had both a distress event and a datable bank loss (n = 135):

- bank loss happened before the event: 88.1% of them
- typical lead time when it did: 59.4 months

Note: cell counts can be small, so read these as indicative, not final.