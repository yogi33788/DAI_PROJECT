# Project decisions and analysis plan

## Question
Does NRRR compare IPL teams more fairly than NRR, especially when teams differ in scoring rates, overs faced, wickets lost, and rain-affected conditions?

## Agreed NRRR definition
Use the formula in the selected article:

\[
RRR_1 = \frac{S_1}{100}\left(1-\frac{S_2}{P_2}\right)
\]

where \(S_1\) is Team 1's score, \(S_2\) is Team 2's score, and \(P_2\) is Team 2's par score based on available resources. Do not replace it with \(\frac{RR_{\mathrm{for}}}{RR_{\mathrm{against}}}-1\).

Reference article: https://cricketbyjb.in/index.php/2025/09/09/nrrr-net-relative-run-rate-cricket-explained/

## Rain-flag policy
Retain all matches in the main dataset. Use rain/revised-condition flags for a clearly labelled sensitivity analysis. Metadata flags are screening indicators, not proof of rainfall. Validate key cases with scorecards or match reports.

## Planned analysis
1. Validate match coverage and season/team labels.
2. Compute official NRR according to applicable IPL rules, explicitly handling all-out and shortened innings.
3. Find/document a valid par-score or resource method before calculating NRRR.
4. Compare NRR and NRRR at team-season level:
   - rank changes and rank correlation;
   - relationship with win rate (descriptive, not proof of fairness);
   - sensitivity with and without revised-condition matches;
   - subgroup analysis by overs faced and wickets lost;
   - uncertainty intervals where appropriate.
5. Document limitations and ensure all results are reproducible from scripts.
