Scenario Structure

We’ll compare two brokers: IBKR (with commissions) and Alpaca (commission-free), and test different risk/leverage levels per trade:

Scenario	Risk per Trade	Leverage	Broker	Trade Costs	Notes
A	1%	None	IBKR	Commissions + slippage	Conservative, low friction
B	1%	None	Alpaca	Slippage only	Conservative, zero commissions
C	3.68% (Safe Kelly)	None	IBKR	Commissions + slippage	Moderate risk, moderate cost
D	3.68%	None	Alpaca	Slippage only	Moderate risk, zero commissions
E	7.36% (Full Kelly)	None	IBKR	Commissions + slippage	Aggressive risk, high cost exposure
F	7.36%	None	Alpaca	Slippage only	Aggressive risk, zero commissions
G	1%	2x	IBKR	Commissions + slippage + leverage cost	Leverage applied, conservative risk
H	1%	2x	Alpaca	Slippage only	Leverage applied, zero commissions
I	3.68%	2x	IBKR	Commissions + slippage + leverage cost	Moderate risk + leverage
J	3.68%	2x	Alpaca	Slippage only	Moderate risk + leverage
K	7.36%	2x	IBKR	Commissions + slippage + leverage cost	High risk + leverage
L	7.36%	2x	Alpaca	Slippage only	High risk + leverage