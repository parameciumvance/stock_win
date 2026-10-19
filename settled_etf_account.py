"""Fractional-share quote accounting with reserved purchases and deferred sale cash.

Numerical settlement scenario only. No brokerage orders, fills, taxes or PIT claim.
"""
from dataclasses import dataclass,field
from decimal import Decimal,localcontext

D=Decimal
EPS=D('1e-23')


def decimal(value):
    result=D(str(value))
    if not result.is_finite():raise ValueError('Nonfinite account input')
    return result


@dataclass
class Account:
    cash:D
    units:D=field(default_factory=lambda:D(0))
    buys:list=field(default_factory=list)
    sales:list=field(default_factory=list)
    dividends:list=field(default_factory=list)

    def __post_init__(self):
        self.cash=decimal(self.cash);self.units=decimal(self.units);self.check()

    @staticmethod
    def total(items):return sum((value for day,value in items),D(0))

    @property
    def payable(self):return self.total(self.buys)

    @property
    def sale_receivable(self):return self.total(self.sales)

    @property
    def dividend_receivable(self):return self.total(self.dividends)

    @property
    def spendable(self):return self.cash-self.payable

    def check(self):
        values=[self.cash,self.units,self.spendable,*[v for items in [self.buys,self.sales,self.dividends] for day,v in items]]
        if any(not v.is_finite() or v < -EPS for v in values):raise ValueError('Negative/nonfinite cash, units or reserved funding')

    def settle(self,day):
        if any(d<day for items in [self.buys,self.sales] for d,v in items):raise ValueError('Missed settlement day')
        buy=sum((v for d,v in self.buys if d==day),D(0));sale=sum((v for d,v in self.sales if d==day),D(0))
        self.cash+=sale-buy;self.buys=[x for x in self.buys if x[0]!=day];self.sales=[x for x in self.sales if x[0]!=day];self.check()
        return buy,sale

    def split(self,ratio):
        ratio=decimal(ratio)
        if ratio<=0:raise ValueError('Invalid split ratio')
        self.units*=ratio

    def ex_dividend(self,day,payment,per_unit):
        per_unit=decimal(per_unit)
        if payment<day or per_unit<=0:raise ValueError('Invalid dividend terms')
        amount=self.units*per_unit
        self.dividends.append((payment,amount));self.check();return amount

    def pay_dividends(self,day):
        if any(d<day for d,v in self.dividends):raise ValueError('Missed dividend payment day')
        paid=sum((v for d,v in self.dividends if d==day),D(0));self.cash+=paid
        self.dividends=[x for x in self.dividends if x[0]!=day];self.check();return paid

    def nav(self,price):
        price=decimal(price)
        if price<=0:raise ValueError('Invalid valuation price')
        return self.units*price+self.cash+self.sale_receivable+self.dividend_receivable-self.payable

    def rebalance(self,day,due,price,target,cost):
        price,target,cost=map(decimal,[price,target,cost])
        if price<=0 or not 0<=target<=1 or not 0<=cost<1 or due<=day:raise ValueError('Invalid target, cost, price or settlement')
        before=self.nav(price);asset=self.units*price
        if before<=0:raise ValueError('Nonpositive account NAV')
        desired=target*before-asset
        delta=desired/(1+target*cost if desired>=0 else 1-target*cost)
        fee=abs(delta)*cost
        result=dict(date=day,due=due,price=str(price),target=str(target),asset_before=str(asset),nav_before=str(before),spendable_before=str(self.spendable),desired_delta=str(delta),status='filled_quote_scenario')
        if abs(delta)<EPS:
            result.update(status='zero_delta',delta='0',shares_delta='0',cost='0');return result
        if delta>0 and delta+fee>self.spendable+EPS:
            result.update(status='rejected_insufficient_spendable_cash',delta='0',shares_delta='0',cost='0');return result
        shares=delta/price
        if self.units+shares < -EPS:raise ValueError('Cannot sell more shares than held')
        self.units+=shares
        if delta>0:self.buys.append((due,delta+fee))
        else:self.sales.append((due,-delta-fee))
        self.check()
        if abs(self.nav(price)-(before-fee))>EPS:raise ValueError('Trade wealth conservation failed')
        if abs(self.units*price-target*self.nav(price))>EPS:raise ValueError('Post-cost target identity failed')
        result.update(delta=str(delta),shares_delta=str(shares),cost=str(fee));return result


def settlement_day(calendar,day,lag=2):
    if len(set(calendar))!=len(calendar) or calendar!=sorted(calendar) or day not in calendar or type(lag)is not int or lag<1:
        raise ValueError('Invalid market calendar or settlement lag')
    index=calendar.index(day)+lag
    if index>=len(calendar):raise ValueError('Insufficient future settlement calendar')
    return calendar[index]


def replay(market,decisions,distributions,split,start,end,initial,cost):
    from datetime import date,timedelta
    calendar=[r['date'] for r in market]
    if len(set(calendar))!=len(calendar) or calendar!=sorted(calendar):raise ValueError('Duplicate/unordered market calendar')
    quotes={r['date']:r for r in market};events={r['ex_date']:r for r in distributions};targets={r['date']:r for r in decisions}
    if len(targets)!=len(decisions) or set(targets)!={d for d in calendar if start<=d<=end}:raise ValueError('Decision calendar mismatch')
    result=[];trades=[];claims=[];last_price=None;quote_date=None
    with localcontext() as context:
        context.prec=40;book=Account(decimal(initial));day=date.fromisoformat(start);last=date.fromisoformat(end)
        while day<=last:
            ds=day.isoformat();settled_buy,settled_sale=book.settle(ds)
            if ds==split['date']:
                book.split(split['ratio'])
                if last_price is not None:last_price/=decimal(split['ratio'])
            claim=D(0)
            if ds in events:
                e=events[ds];claim=book.ex_dividend(ds,e['payment_date'],e['cash_per_unit'])
                claims.append(dict(ex_date=ds,payment_date=e['payment_date'],entitled_units=str(book.units),amount=str(claim)))
            q=quotes.get(ds);decision=targets.get(ds)
            def quoted(key):return q is not None and q[key] not in ['',None,'nan','NaN']
            if decision is not None and decision['target'] not in ['',None,'nan','NaN']:
                if not quoted('open') or decision['reason']!='rebalance':raise ValueError('Frozen target on unquoted or nonscheduled date')
                trades.append(book.rebalance(ds,settlement_day(calendar,ds),q['open'],decision['target'],cost))
            if quoted('close'):last_price=decimal(q['close']);quote_date=ds
            if last_price is None:raise ValueError('No initial quote for valuation')
            paid=book.pay_dividends(ds);wealth=book.nav(last_price)
            result.append(dict(date=ds,market_session=ds in targets,carried_market_valuation=ds in targets and not quoted('close'),last_quote_date=quote_date,
                units=str(book.units),raw_close=str(last_price),bank_cash=str(book.cash),purchase_payable=str(book.payable),sale_receivable=str(book.sale_receivable),
                dividend_receivable=str(book.dividend_receivable),spendable_cash=str(book.spendable),wealth=str(wealth),paid_dividend=str(paid),new_claim=str(claim),settled_buy=str(settled_buy),settled_sale=str(settled_sale)))
            day+=timedelta(days=1)
    return dict(daily=result,trades=trades,claims=claims)
