"""TASK 3.4 -- bootstrapping mechanism edges from input-output tables.

    Supply-Use Table
          |  normalise to direct input coefficients a(A->B)
    INDUSTRY INPUT MATRIX  (~130 x 130)
          |  Leontief inverse (I - A)^-1 -> total requirements
    TOTAL REQUIREMENT MATRIX
          |  map NIC/IOTT industry codes -> sector_id -> exposure_tag
    CANDIDATE MECHANISM EDGES  (with a coefficient, not a guess)
          |  human review: keep / discard / rename the mechanism
    CAUSAL GRAPH EDGES

The Leontief inverse is the part that matters. Direct coefficients give
first-round exposure (paints buy petrochemicals). The inverse gives TOTAL
exposure including every indirect round (paints buy packaging which buys
plastics which buys petrochemicals) -- second- and third-order transmission
COMPUTED rather than imagined.

`io_coefficient` SHIPS EMPTY AND STAYS EMPTY. Everything in this package is
machinery: a parser, linear algebra, a pruning rule, an industry mapping and
a review queue. Not one coefficient is written from anybody's memory. The
phase file is explicit -- "Do not populate io_coefficient from memory. It
comes from published tables or the table stays empty" -- and DATA_GAPS §7
names the tables, the owner and the acquisition work.

WHAT IO TABLES CANNOT DO (A2.4, stated so nobody discovers it later). They
model COST STRUCTURE, so they generate INPUT_COST and DEMAND edges well.
They generate no REVENUE_REALIZATION, FX, rate or regulatory edge at all.
Those stay hand-authored -- roughly 60-100 of them -- and no amount of IO
data will produce them.
"""
