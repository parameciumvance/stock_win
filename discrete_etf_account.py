"""Integer final-holding grids on a frozen cash-settlement account, never live orders."""
from decimal import Decimal as D,localcontext
from fractions import Fraction as F

from settled_etf_account import Account,EPS,decimal,settlement_day


class DiscreteAccount(Account):
    def __init__(self,cash,unit):
        if type(unit)is not int or unit<=0:raise ValueError('Quantity unit must be a positive integer')
        self.unit=unit;super().__init__(cash)

    def split(self,ratio):
        super().split(ratio)
        if self.units % self.unit:raise ValueError('Split creates unsupported off-grid holdings')

    def rebalance(self,day,due,price,target,cost):
        price,target,cost=map(decimal,[price,target,cost])
        if price<=0 or not 0<=target<=1 or not 0<=cost<1 or due<=day:raise ValueError('Invalid price,target,cost or settlement')
        if self.units%self.unit:raise ValueError('Pretrade holdings off quantity grid')
        before=self.nav(price);original_units=self.units;asset=self.units*price
        if before<=0:raise ValueError('Nonpositive NAV')
        desired=F(target)*F(before)-F(asset)
        ideal_delta=desired/(1+F(target)*F(cost) if desired>=0 else 1-F(target)*F(cost))
        ideal_final=F(self.units)+ideal_delta/F(price)
        chosen=(ideal_final//self.unit)*self.unit
        if chosen<0:raise ValueError('Negative rounded target')
        shares=D(chosen)-self.units;delta=shares*price;fee=abs(delta)*cost
        result=dict(date=day,due=due,price=str(price),target=str(target),asset_before=str(asset),nav_before=str(before),spendable_before=str(self.spendable),
            desired_delta=str(D(ideal_delta.numerator)/D(ideal_delta.denominator)),status='filled_quote_scenario',quantity_unit=self.unit,
            ideal_final_shares_exact=str(ideal_final),rounded_final_shares=chosen)
        if shares==0:
            result.update(status='rounded_no_change' if ideal_delta else 'zero_delta',delta='0',shares_delta='0',cost='0');return result
        if delta>0 and delta+fee>self.spendable+EPS:
            result.update(status='rejected_insufficient_spendable_cash',delta='0',shares_delta='0',cost='0');return result
        self.units+=shares
        if delta>0:self.buys.append((due,delta+fee))
        else:self.sales.append((due,-delta-fee))
        self.check()
        if self.units%self.unit or abs(self.nav(price)-(before-fee))>EPS:raise ValueError('Grid or wealth conservation failure')
        # The floor is conservative. One further unit would exceed the post-cost target.
        if F(self.units)*F(price)>F(target)*F(self.nav(price))+F(EPS):raise ValueError('Rounded holdings exceed target')
        nxt=F(self.units+self.unit);next_value=(nxt-F(original_units))*F(price)
        if nxt*F(price)<=F(target)*(F(before)-abs(next_value)*F(cost)):raise ValueError('Rounding did not choose largest admissible grid holding')
        result.update(delta=str(delta),shares_delta=str(shares),cost=str(fee));return result


def replay_grid(market,decisions,distributions,split,start,end,initial,cost,unit):
    """Same event order as the frozen fractional replay, with injectable quantity sizing.

    The unit=None path must match every prior saved field exactly before accepting
    any integer case. The original source file remains frozen and unmodified.
    """
    from datetime import date,timedelta
    calendar=[r['date'] for r in market]
    if len(set(calendar))!=len(calendar) or calendar!=sorted(calendar):raise ValueError('Duplicate/unordered market calendar')
    quotes={r['date']:r for r in market};events={r['ex_date']:r for r in distributions};targets={r['date']:r for r in decisions}
    if len(targets)!=len(decisions) or set(targets)!={d for d in calendar if start<=d<=end}:raise ValueError('Decision calendar mismatch')
    result=[];trades=[];claims=[];last_price=None;quote_date=None
    with localcontext() as context:
        context.prec=40;book=Account(decimal(initial)) if unit is None else DiscreteAccount(decimal(initial),unit)
        day=date.fromisoformat(start);last=date.fromisoformat(end)
        while day<=last:
            ds=day.isoformat();settled_buy,settled_sale=book.settle(ds)
            if ds==split['date']:
                book.split(split['ratio'])
                if last_price is not None:last_price/=decimal(split['ratio'])
            claim=D(0)
            if ds in events:
                event=events[ds];claim=book.ex_dividend(ds,event['payment_date'],event['cash_per_unit'])
                claims.append(dict(ex_date=ds,payment_date=event['payment_date'],entitled_units=str(book.units),amount=str(claim)))
            quote=quotes.get(ds);decision=targets.get(ds)
            def quoted(key):return quote is not None and quote[key] not in ['',None,'nan','NaN']
            if decision is not None and decision['target'] not in ['',None,'nan','NaN']:
                if not quoted('open') or decision['reason']!='rebalance':raise ValueError('Frozen target on unquoted or nonscheduled date')
                trades.append(book.rebalance(ds,settlement_day(calendar,ds),quote['open'],decision['target'],cost))
            if quoted('close'):last_price=decimal(quote['close']);quote_date=ds
            if last_price is None:raise ValueError('No initial quote for valuation')
            paid=book.pay_dividends(ds);wealth=book.nav(last_price)
            result.append(dict(date=ds,market_session=ds in targets,carried_market_valuation=ds in targets and not quoted('close'),last_quote_date=quote_date,
                units=str(book.units),raw_close=str(last_price),bank_cash=str(book.cash),purchase_payable=str(book.payable),sale_receivable=str(book.sale_receivable),
                dividend_receivable=str(book.dividend_receivable),spendable_cash=str(book.spendable),wealth=str(wealth),paid_dividend=str(paid),new_claim=str(claim),settled_buy=str(settled_buy),settled_sale=str(settled_sale)))
            day+=timedelta(days=1)
    return dict(daily=result,trades=trades,claims=claims)
