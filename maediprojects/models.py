import datetime
import functools as ft
import collections

import sqlalchemy as sa
from sqlalchemy import func, union_all
from sqlalchemy.orm import validates, aliased
from sqlalchemy.sql.expression import case
from sqlalchemy.ext.hybrid import hybrid_property
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import current_user
from maediprojects.lib import util, codelist_helpers
from flask import url_for

from maediprojects.extensions import db


cascade_relationship = ft.partial(
    sa.orm.relationship,
    passive_deletes=True,
)

act_ForeignKey = ft.partial(
    sa.ForeignKey,
    ondelete="CASCADE"
)

# Adapted from here:
# https://stackoverflow.com/questions/42552696/sqlalchemy-nearest-datetime
def get_closest_date(the_date, the_currency):
    """
    Returns the highest-scoring conversion rate. The score is derived from:
      * the proximity to the requested date `the_date` for a given
        currency `the_currency`
      * multiplied by a score given to each exchange rate source.

    For example, we set FRED (daily) rates to have a score of 1 and
    OECD (monthly) rates to have a score of 33. This means a FRED rate can
    have a date up to 33 days further away from the requested date to score
    the same as an OECD rate on the same day as the requested date.
    """
    greater = db.session.query(ExchangeRate
        ).filter(ExchangeRate.rate_date > the_date,
            Currency.code == the_currency
        ).join(Currency
        ).order_by(ExchangeRate.rate_date.asc()).limit(30).subquery().select()

    lesser = db.session.query(ExchangeRate
        ).filter(ExchangeRate.rate_date <= the_date,
            Currency.code == the_currency
        ).join(Currency
        ).order_by(ExchangeRate.rate_date.desc()).limit(30).subquery().select()

    the_union = union_all(lesser, greater).alias()
    the_alias = aliased(ExchangeRate, the_union)
    abs_diff = func.abs(func.julianday(getattr(the_alias, "rate_date")) - func.julianday(the_date))
    score_alias = aliased(ExchangeRateSource, the_union)
    abs_score = (func.abs(getattr(score_alias, "weight")) *
        1+(func.abs(func.julianday(getattr(the_alias, "rate_date")) -
            func.julianday(the_date))))

    return db.session.query(the_alias,
        abs_diff,
        abs_score
        ).join(ExchangeRateSource, the_alias.exchangeratesource_id == ExchangeRateSource.id
        ).join(Currency, the_alias.currency_code == Currency.code
        ).filter(Currency.code == the_currency
        ).order_by(abs_score.asc()
        ).first()

def fwddata_query(_self, fiscalyear_modifier):
    QUERY_COLS = (func.sum(ActivityForwardSpend.value).label("value"),
                func.STRFTIME('%Y',
                    func.DATE(ActivityForwardSpend.period_start_date,
                        'start of month', '-{} month'.format(fiscalyear_modifier))
                    ).label("fiscal_year"),
                case(
                    [
                        (func.STRFTIME('%m', func.DATE(ActivityForwardSpend.period_start_date,
                          'start of month', '-{} month'.format(fiscalyear_modifier))
                            ).in_(('01','02','03')), 'Q1'),
                        (func.STRFTIME('%m', func.DATE(ActivityForwardSpend.period_start_date,
                          'start of month', '-{} month'.format(fiscalyear_modifier))
                            ).in_(('04','05','06')), 'Q2'),
                        (func.STRFTIME('%m', func.DATE(ActivityForwardSpend.period_start_date,
                          'start of month', '-{} month'.format(fiscalyear_modifier))
                            ).in_(('07','08','09')), 'Q3'),
                        (func.STRFTIME('%m', func.DATE(ActivityForwardSpend.period_start_date,
                          'start of month', '-{} month'.format(fiscalyear_modifier))
                            ).in_(('10','11','12')), 'Q4'),
                    ]
                ).label("fiscal_quarter"))
    return db.session.query(
            *QUERY_COLS
        ).filter(
            ActivityForwardSpend.activity_id == _self.id,
            ActivityForwardSpend.value != 0
        ).group_by("fiscal_quarter", "fiscal_year"
        ).order_by(ActivityForwardSpend.period_start_date.desc()
        ).all()


def fydata_query(_self, fiscalyear_modifier, _transaction_types, fund_sources=False):
    QUERY_COLS = (func.sum(ActivityFinances.transaction_value).label("value"),
            func.STRFTIME('%Y',
                func.DATE(ActivityFinances.transaction_date,
                    'start of month', '-{} month'.format(fiscalyear_modifier))
                ).label("fiscal_year"),
            case(
                [
                    (func.STRFTIME('%m', func.DATE(ActivityFinances.transaction_date,
                      'start of month', '-{} month'.format(fiscalyear_modifier))
                        ).in_(('01','02','03')), 'Q1'),
                    (func.STRFTIME('%m', func.DATE(ActivityFinances.transaction_date,
                      'start of month', '-{} month'.format(fiscalyear_modifier))
                        ).in_(('04','05','06')), 'Q2'),
                    (func.STRFTIME('%m', func.DATE(ActivityFinances.transaction_date,
                      'start of month', '-{} month'.format(fiscalyear_modifier))
                        ).in_(('07','08','09')), 'Q3'),
                    (func.STRFTIME('%m', func.DATE(ActivityFinances.transaction_date,
                      'start of month', '-{} month'.format(fiscalyear_modifier))
                        ).in_(('10','11','12')), 'Q4'),
                ]
            ).label("fiscal_quarter"))
    GROUP_BYS = ("fiscal_quarter", "fiscal_year")
    if fund_sources:
        QUERY_COLS += (FundSource.name.label("fund_source_name"),)
        GROUP_BYS += ("fund_source_name",)

    query = db.session.query(
            *QUERY_COLS
        )
    if fund_sources:
        query = query.outerjoin(FundSource, ActivityFinances.fund_source_id==FundSource.id
        )
    return query.filter(
            ActivityFinances.activity_id == _self.id,
            ActivityFinances.transaction_value != 0,
            ActivityFinances.transaction_type.in_(_transaction_types)
        ).group_by(*GROUP_BYS
        ).order_by(ActivityFinances.transaction_date.desc()
        ).all()


class Currency(db.Model):
    __tablename__ = 'currency'
    code = sa.Column(sa.UnicodeText,
        nullable=False, primary_key=True)
    name = sa.Column(sa.UnicodeText,
        nullable=False)

    def as_dict(self):
        return ({c.name: getattr(self, c.name) for c in self.__table__.columns})


class ExchangeRateSource(db.Model):
    __tablename__ = 'exchangeratesource'
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.UnicodeText, nullable=False)
    weight = sa.Column(sa.Float,
        default=1, nullable=False)

    def as_dict(self):
        return ({c.name: getattr(self, c.name) for c in self.__table__.columns})


class ExchangeRate(db.Model):
    __tablename__ = 'exchangerate'
    id = sa.Column(sa.Integer, primary_key=True)
    exchangeratesource_id = sa.Column(
        act_ForeignKey('exchangeratesource.id'),
        nullable=False, index=True)
    exchangeratesource = sa.orm.relationship("ExchangeRateSource")
    currency_code = sa.Column(
        act_ForeignKey('currency.code'),
        nullable=False, index=True)
    currency = sa.orm.relationship("Currency")
    rate_date = sa.Column(sa.Date,
        nullable=False, index=True)
    rate = sa.Column(sa.Float, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('exchangeratesource_id', 'currency_code', 'rate_date', name='unique_exchange_rate'),
    )

    def as_dict(self):
       ret_data = {}
       ret_data.update({c.name: getattr(self, c.name) for c in self.__table__.columns})
       ret_data.update({key: getattr(self, key).as_dict() for key in self.__mapper__.relationships.keys()})
       return ret_data


class ActivityDocumentLink(db.Model):
    __tablename__ = 'activitydocumentlink'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(
        act_ForeignKey('activity.id'),
        nullable=False, index=True)
    title = sa.Column(sa.UnicodeText)
    url = sa.Column(sa.UnicodeText)
    categories = sa.orm.relationship("ActivityDocumentLinkCategory",
            cascade="all, delete-orphan")
    document_date = sa.Column(sa.Date)

    def as_dict(self):
        return ({c.name: getattr(self, c.name) for c in self.__table__.columns})


class ActivityDocumentLinkCategory(db.Model):
    __tablename__ = 'activitydocumentlinkcategory'
    id = sa.Column(sa.Integer, primary_key=True)
    activitydocumentlink_id = sa.Column(
        act_ForeignKey('activitydocumentlink.id'),
        nullable=False, index=True)
    code = sa.Column(sa.UnicodeText)


class Activity(db.Model):
    __tablename__ = 'activity'
    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(
            act_ForeignKey('maediuser.id'),
            nullable=False,
            index=True)
    user = sa.orm.relationship("User")
    code = sa.Column(sa.UnicodeText)
    title = sa.Column(sa.UnicodeText)
    description = sa.Column(sa.UnicodeText)
    start_date = sa.Column(sa.Date)
    end_date = sa.Column(sa.Date)
    organisations = sa.orm.relationship("ActivityOrganisation",
            cascade="all, delete-orphan")
    reporting_org_id = sa.Column(
            act_ForeignKey('organisation.id'),
            nullable=False,
            index=True)
    reporting_org = sa.orm.relationship("Organisation",
            foreign_keys=[reporting_org_id],
            backref="activities_as_reporting_org")
    implementing_org = sa.Column(sa.UnicodeText) # ADDED
    recipient_country_code = sa.Column(
            act_ForeignKey('country.code'),
            nullable=False,
            index=True)
    recipient_country = sa.orm.relationship("Country")
    dac_sector = sa.Column(sa.UnicodeText)
    collaboration_type = sa.Column(sa.UnicodeText) # ADDED
    finance_type = sa.Column(sa.UnicodeText) # ADDED
    tied_status = sa.Column(sa.UnicodeText) # ADDED
    flow_type = sa.Column(sa.UnicodeText)
    aid_type = sa.Column(sa.UnicodeText)
    activity_status = sa.Column(sa.UnicodeText)
    total_commitments = sa.Column(sa.Float(precision=2))
    total_disbursements = sa.Column(sa.Float(precision=2))
    created_date = sa.Column(sa.DateTime, default=datetime.datetime.utcnow) # ADDED
    updated_date = sa.Column(sa.DateTime, default=datetime.datetime.utcnow) # ADDED
    results = sa.orm.relationship("ActivityResult",
            cascade="all, delete-orphan",
            backref="activity")
    locations = sa.orm.relationship("ActivityLocation",
            cascade="all, delete-orphan",
            backref="activity")
    finances = sa.orm.relationship("ActivityFinances",
            cascade="all, delete-orphan")
    forwardspends = sa.orm.relationship("ActivityForwardSpend",
            cascade="all, delete-orphan")
    classifications = sa.orm.relationship("ActivityCodelistCode",
            cascade="all, delete-orphan")
    milestones = sa.orm.relationship("ActivityMilestone",
            cascade="all, delete-orphan",
            backref="activity")
    counterpart_funding = sa.orm.relationship("ActivityCounterpartFunding",
            cascade="all, delete-orphan")
    domestic_external = sa.Column(sa.UnicodeText)

    documents = sa.orm.relationship("ActivityDocumentLink",
            cascade="all, delete-orphan")
    activity_logs = cascade_relationship(
        "ActivityLog",
        backref="activity")

    @hybrid_property
    def permissions(self):
        # TODO eventually this will vary by activity, as permissions can be
        # selective for different organisations.
        def _check_org_permission():
            org_permission = self.reporting_org_id in current_user.permissions_dict.get("organisations", [])
            if org_permission:
                return current_user.permissions_dict["organisations"][self.reporting_org_id]["permission_value"]
            return False
        op = _check_org_permission()
        return {
        "edit": (("admin" in current_user.roles_list) or
            (current_user.permissions_dict["edit"] == "both") or
            (current_user.permissions_dict["edit"] == self.domestic_external) or
            (op=="edit")),
        "view": (("admin" in current_user.roles_list) or
            (current_user.permissions_dict["view"] != "none") or
            (current_user.permissions_dict["view"] == self.domestic_external) or
            (op in ("view", "edit")))
        }

    implementing_organisations = sa.orm.relationship("Organisation",
        secondary="activityorganisation",
        secondaryjoin="""and_(ActivityOrganisation.role==4,
            ActivityOrganisation.organisation_id==Organisation.id)"""
        )

    funding_organisations = sa.orm.relationship("Organisation",
        secondary="activityorganisation",
        secondaryjoin="""and_(ActivityOrganisation.role==1,
            ActivityOrganisation.organisation_id==Organisation.id)"""
        )

    @hybrid_property
    def disb_finance_types(self):
        query = db.session.query(
            sa.func.sum(ActivityFinances.transaction_value).label("sum_value"),
            ActivityFinances.finance_type
            ).outerjoin(FundSource, ActivityFinances.fund_source_id == FundSource.id
            ).group_by(ActivityFinances.finance_type
            ).filter(ActivityFinances.transaction_type==u"D"
            ).filter(ActivityFinances.activity_id==self.id
            ).all()
        data = dict(map(lambda ft: (ft.finance_type, ft.sum_value), query))
        total = sum(map(lambda ft: ft.sum_value, query))
        if total == 0: return { "Grant": 0.0, "Loan": 0.0 }
        return {
            "Grant": int(round((data.get(u"110", 0) / total)*100)),
            "Loan": int(round((data.get("410", 0) / total)*100)),
        }

    @hybrid_property
    def disb_fund_sources(self):
        query = db.session.query(
            sa.func.sum(ActivityFinances.transaction_value).label("sum_value"),
                FundSource.name,
                ActivityFinances.finance_type
            ).outerjoin(FundSource, ActivityFinances.fund_source_id == FundSource.id
            ).group_by(FundSource.name, FundSource.finance_type
            ).filter(ActivityFinances.transaction_type==u"D"
            ).filter(ActivityFinances.activity_id==self.id
            ).all()
        total = sum(map(lambda ft: ft.sum_value, query))
        if total == 0: return { "": { "value": 0.0}}
        return dict(map(lambda ft: (ft.name, {
                "value": int(round((ft.sum_value / total)*100)),
                "finance_type": {
                    "110": "Grant",
                    "410": "Loan",
                }.get(ft.finance_type)
            }), query))

    @hybrid_property
    def total_commitments(self):
        return db.session.query(sa.func.sum(ActivityFinances.transaction_value)
                        ).filter(ActivityFinances.transaction_type==u"C",
                         ActivityFinances.activity_id==self.id).scalar()
    @hybrid_property
    def total_disbursements(self):
        return db.session.query(sa.func.sum(ActivityFinances.transaction_value)
                        ).filter(ActivityFinances.transaction_type==u"D",
                         ActivityFinances.activity_id==self.id).scalar()

    commitments = sa.orm.relationship("ActivityFinances",
        primaryjoin="""and_(ActivityFinances.activity_id==Activity.id,
        ActivityFinances.transaction_type==u'C')""")
    allotments = sa.orm.relationship("ActivityFinances",
        primaryjoin="""and_(ActivityFinances.activity_id==Activity.id,
        ActivityFinances.transaction_type==u'99-A')""")
    disbursements = sa.orm.relationship("ActivityFinances",
        primaryjoin="""and_(ActivityFinances.activity_id==Activity.id,
        ActivityFinances.transaction_type==u'D')""")

    result_indicator_periods = sa.orm.relationship("ActivityResultIndicatorPeriod",
        secondary="join(ActivityResultIndicator, ActivityResult, ActivityResult.id == ActivityResultIndicator.result_id)",
        primaryjoin="and_(Activity.id == ActivityResult.activity_id, ActivityResult.id == ActivityResultIndicator.result_id)",
        secondaryjoin="ActivityResultIndicator.id == ActivityResultIndicatorPeriod.indicator_id",
        viewonly = True
        )

    @hybrid_property
    def results_average(self):
        numerical_periods = filter(lambda ip: ip.percent_complete != None, self.result_indicator_periods)
        if not numerical_periods: return None
        return sum(list(map(lambda ip: ip.percent_complete, numerical_periods)))/len(numerical_periods)

    @hybrid_property
    def results_average_status(self):
        return "primary"
        if self.results_average is not None:
            if self.results_average >= 80:
                return "success"
            elif self.results_average >= 40:
                return "warning"
            else:
                return "danger"
        return None

    def FY_disbursements_for_FY(self, FY):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        result = db.session.query(
                func.sum(ActivityFinances.transaction_value).label("value")
            ).filter(
                ActivityFinances.activity_id == self.id,
                ActivityFinances.transaction_type.in_((u'D', u'E')),
                func.STRFTIME('%Y',
                    func.DATE(ActivityFinances.transaction_date,
                        'start of month', '-{} month'.format(fiscalyear_modifier))
                    ) == FY
            ).scalar()
        if result is None: return 0.00
        return result

    def FY_forwardspends_for_FY(self, FY):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        result = db.session.query(
                func.sum(ActivityForwardSpend.value).label("value")
            ).filter(
                ActivityForwardSpend.activity_id == self.id,
                func.STRFTIME('%Y',
                    func.DATE(ActivityForwardSpend.period_start_date,
                        'start of month', '-{} month'.format(fiscalyear_modifier))
                    ) == FY
            ).scalar()
        if result is None: return 0.00
        return result

    def FY_counterpart_funding_for_FY(self, FY):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        result = db.session.query(
                func.sum(ActivityCounterpartFunding.required_value).label("value")
            ).filter(
                ActivityCounterpartFunding.activity_id == self.id,
                func.STRFTIME('%Y',
                    func.DATE(ActivityCounterpartFunding.required_date,
                        'start of month', '-{} month'.format(fiscalyear_modifier))
                    ) == FY
            ).scalar()
        if result is None: return 0.00
        return result

    @hybrid_property
    def FY_disbursements_dict(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fydata_query(self, fiscalyear_modifier, [u'D', u'E'])

        return {
                    "{} {} (D)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "date": util.fq_fy_to_date(int(fyval.fiscal_quarter[1:]), int(fyval.fiscal_year), 'end'),
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                    }
                    for fyval in fydata
                }

    @hybrid_property
    def FY_disbursements_dict_fund_sources(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fydata_query(self, fiscalyear_modifier, [u'D', u'E'], True)

        out = collections.defaultdict(dict)
        for fyval in fydata:
            out[fyval.fund_source_name].update({
                "{} {} (D)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "date": util.fq_fy_to_date(int(fyval.fiscal_quarter[1:]), int(fyval.fiscal_year), 'end'),
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                }}
            )
        return out

    @hybrid_property
    def FY_allotments_dict(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fydata_query(self, fiscalyear_modifier, [u'99-A'])

        return {
                    "{} {} (99-A)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "date": util.fq_fy_to_date(int(fyval.fiscal_quarter[1:]), int(fyval.fiscal_year), 'end'),
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                    }
                    for fyval in fydata
                }

    @hybrid_property
    def FY_allotments_dict_fund_sources(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fydata_query(self, fiscalyear_modifier, [u'99-A'], True)

        out = collections.defaultdict(dict)
        for fyval in fydata:
            out[fyval.fund_source_name].update({
                "{} {} (99-A)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "date": util.fq_fy_to_date(int(fyval.fiscal_quarter[1:]), int(fyval.fiscal_year), 'end'),
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                }}
            )
        return out

    @hybrid_property
    def FY_commitments_dict(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fydata_query(self, fiscalyear_modifier, [u'C'])
        return {
                    "{} {} (C)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "date": util.fq_fy_to_date(int(fyval.fiscal_quarter[1:]), int(fyval.fiscal_year), 'end'),
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                    }
                    for fyval in fydata
                }

    @hybrid_property
    def FY_commitments_dict_fund_sources(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fydata_query(self, fiscalyear_modifier, [u'C'], True)

        out = collections.defaultdict(dict)
        for fyval in fydata:
            out[fyval.fund_source_name].update({
                "{} {} (C)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "date": util.fq_fy_to_date(int(fyval.fiscal_quarter[1:]), int(fyval.fiscal_year), 'end'),
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                }}
            )
        return out

    @hybrid_property
    def FY_forward_spend_dict_fund_sources(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fwddata_query(self, fiscalyear_modifier)
        return {
            None: {
                "{} {} (MTEF)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                }
                for fyval in fydata
            }
        }

    @hybrid_property
    def FY_forward_spend_dict(self):
        fiscalyear_modifier = 6 #FIXME this is just for Liberia
        fydata = fwddata_query(self, fiscalyear_modifier)
        return {
                    "{} {} (MTEF)".format(fyval.fiscal_year, fyval.fiscal_quarter): {
                    "fiscal_year": fyval.fiscal_year,
                    "fiscal_quarter": fyval.fiscal_quarter,
                    "period": "FY{} {}".format(fyval.fiscal_year, fyval.fiscal_quarter),
                    "value": round(fyval.value, 4)
                    }
                    for fyval in fydata
                }

    @hybrid_property
    def classification_data(self):
        def append_path(root, classification):
            if classification:
                sector = root.setdefault("{}".format(classification.codelist_code.codelist.code),
                    { "entries": [],
                      "name": classification.codelist_code.codelist.name,
                      "code": classification.codelist_code.codelist.code,
                      "id": classification.id
                    }
                )
                sector["entries"].append(classification)
        root = {}
        for s in self.classifications: append_path(root, s)
        return root

    @hybrid_property
    def milestones_data(self):
        all_milestones = Milestone.query.filter_by(
            domestic_external = self.domestic_external
        ).order_by(Milestone.milestone_order
        ).all()

        ms_achieved = dict(map(lambda ms: (ms.milestone.id, ms.achieved), self.milestones))
        ms_achieved_notes = dict(map(lambda ms: (ms.milestone.id, ms.notes), self.milestones))

        ms = list(map(lambda ms: {
            "name": ms.name,
            "id": ms.id,
            "notes": ms_achieved_notes.get(ms.id, ""),
            "achieved": {
                True: {"status": True, "name": "Completed", "icon": "fa-check-circle", "colour": "success"},
                False: {"status": False, "name": "Pending", "icon": "fa-times-circle", "colour": "warning"},
                }[bool(ms_achieved.get(ms.id, False))]}, all_milestones))
        return ms

    def as_dict(self):
        return ({c.name: getattr(self, c.name) for c in self.__table__.columns})

    def as_jsonable_dict(self):
        role_names = dict((v,k) for k,v in codelist_helpers.codelists("OrganisationRole").iteritems())
        ret_data = {
            'classifications': collections.defaultdict(dict),
            'organisations': collections.defaultdict(dict),
            'url': url_for("activities.activity", activity_id=self.id),
            'url_edit': url_for("activities.activity_edit", activity_id=self.id),
            'results': len(self.results),
            'documents': len(self.documents),
            'milestones': len(self.milestones)
        }
        ret_data.update({c.name: getattr(self, c.name) for c in self.__table__.columns})
        for cc in self.classifications:
            if cc.codelist_code.codelist_code not in ret_data['classifications']:
                ret_data['classifications'][cc.codelist_code.codelist_code] = {
                    'codelist':cc.codelist_code.codelist_code,
                    'name': cc.codelist_code.codelist.name,
                    'entries': []
                }
            ret_data['classifications'][cc.codelist_code.codelist_code]['entries'].append(
                {
                'codelist': cc.codelist_code.codelist_code,
                'code': cc.codelist_code.id,
                'percentage': cc.percentage,
                'activitycodelist_id': cc.id
                })
        for org in self.organisations:
            if org.role not in ret_data['organisations']:
                ret_data['organisations'][org.role] = {
                    'role': org.role,
                    'name': role_names[str(org.role)],
                    'entries': []
                }
            ret_data['organisations'][org.role]['entries'].append(
                {
                'role': org.role,
                'id': org.organisation_id,
                'percentage': org.percentage,
                'activityorganisation_id': org.id})
        return ret_data

class ActivityFinances(db.Model):
    __tablename__ = 'activityfinances'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(sa.Integer,
            sa.ForeignKey('activity.id'),
            nullable=False,
            index=True)
    activity = sa.orm.relationship("Activity")
    currency = sa.Column(sa.UnicodeText, default=u"USD")
    transaction_date = sa.Column(sa.Date)
    transaction_type = sa.Column(sa.UnicodeText,
            index=True)
    transaction_description = sa.Column(sa.UnicodeText)
    transaction_value = sa.Column(sa.Float(precision=2))
    finance_type = sa.Column(sa.UnicodeText)
    aid_type = sa.Column(sa.UnicodeText)
    provider_org_id = sa.Column(sa.Integer,
            sa.ForeignKey('organisation.id'),
            nullable=False)
    provider_org = sa.orm.relationship("Organisation",
            foreign_keys=[provider_org_id])
    receiver_org_id = sa.Column(sa.Integer,
            sa.ForeignKey('organisation.id'),
            nullable=False)
    receiver_org = sa.orm.relationship("Organisation",
            foreign_keys=[receiver_org_id])
    classifications = sa.orm.relationship("ActivityFinancesCodelistCode",
            cascade="all, delete-orphan",
            backref="activityfinances")
    fund_source_id = sa.Column(sa.Integer,
            sa.ForeignKey('fund_source.id'),
            nullable=True)
    transaction_value_original = sa.Column(sa.Float(precision=2),
        default=0, nullable=False)
    currency_automatic = sa.Column(sa.Boolean,
        default=True, nullable=False)
    currency_source = sa.Column(sa.UnicodeText,
        default=u"USD", nullable=False)
    currency_rate = sa.Column(sa.Float,
        default=1.0, nullable=False)
    currency_value_date = sa.Column(sa.Date)

    @validates("currency_rate")
    def update_transaction_value_rate(self, key, currency_rate):
        if self.transaction_value_original and currency_rate:
            self.transaction_value = float(currency_rate)*float(self.transaction_value_original)
        return currency_rate

    @validates("transaction_value_original")
    def update_transaction_value_original(self, key, transaction_value_original):
        if self.currency_rate and transaction_value_original:
            self.transaction_value = float(self.currency_rate)*float(transaction_value_original)
        return transaction_value_original

    @hybrid_property
    def disaggregated_transactions(self):
        _funding_orgs = [self.provider_org,self.provider_org] or self.activity.funding_organisations
        funding_pcts = [{"pct": 1.0/len(_funding_orgs), "obj": f} for f in _funding_orgs]
        _receiving_orgs = [self.receiver_org] or self.activity.implementing_organisations
        receiving_pcts = [{"pct": 1.0/len(_receiving_orgs), "obj": r} for r in _receiving_orgs]
        class DisaggregatedTransaction(ActivityFinances):
            def __init__(self,f,r,transaction):
                pct_modifier = f["pct"]*r["pct"]
                self.activity = transaction.activity
                self.provider_org = f["obj"],
                self.receiver_org = r["obj"],
                self.value = transaction.transaction_value*pct_modifier
        return [DisaggregatedTransaction(f,r,self)
            for r in receiving_pcts
            for f in funding_pcts]

    @hybrid_property
    def mtef_sector(self):
        mtef = ActivityFinancesCodelistCode.query.filter_by(
                    activityfinance_id = self.id,
                    codelist_id = u"mtef-sector"
                    ).first()
        if mtef: return mtef.codelist_code_id
        return ""

    def as_dict(self):
        ret_data = {}
        ret_data.update({c.name: getattr(self, c.name) for c in self.__table__.columns})
        ret_data.update({key: getattr(self, key).as_dict() for key in ['provider_org', 'receiver_org']})
        [ret_data.update({key: [c.as_dict() for c in getattr(self, key)]}) for key in ['classifications']]
        ret_data["mtef_sector"] = self.mtef_sector
        return ret_data

    def as_simple_dict(self):
        ret_data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        ret_data["mtef_sector"] = self.mtef_sector
        return ret_data

class ActivityForwardSpend(db.Model):
    __tablename__ = 'forwardspend' # 'activityforwardspend'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(
        act_ForeignKey("activity.id"),
        nullable=False)
    value = sa.Column(sa.Float(precision=2))
    value_date = sa.Column(sa.Date)
    value_currency = sa.Column(sa.UnicodeText)
    period_start_date = sa.Column(sa.Date)
    period_end_date = sa.Column(sa.Date)

    __table_args__ = (
        sa.UniqueConstraint('activity_id','period_start_date', name='forward_spend_constraint'),
    )

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class FundSource(db.Model):
    __tablename__ = 'fund_source'
    id = sa.Column(sa.Integer, primary_key=True)
    code = sa.Column(sa.UnicodeText, index=True, unique=True)
    name = sa.Column(sa.UnicodeText)
    finance_type = sa.Column(sa.UnicodeText)
    activityfinances = sa.orm.relationship("ActivityFinances",
            backref="fund_source")

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class Country(db.Model):
    __tablename__ = 'country'
    code = sa.Column(sa.UnicodeText, primary_key=True)
    name = sa.Column(sa.UnicodeText)
    locations = sa.orm.relationship("Location",
            cascade="all, delete-orphan",
            backref="country")

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class Location(db.Model):
    __tablename__ = 'location'
    id = sa.Column(sa.Integer, primary_key=True)
    geonames_id = sa.Column(sa.Integer)
    country_code = sa.Column(
            act_ForeignKey('country.code'),
            nullable=False,
            index=True)
    name = sa.Column(sa.UnicodeText)
    latitude = sa.Column(sa.UnicodeText)
    longitude = sa.Column(sa.UnicodeText)
    feature_code = sa.Column(sa.UnicodeText)
    admin1_code = sa.Column(sa.UnicodeText)
    admin2_code = sa.Column(sa.UnicodeText)
    admin3_code = sa.Column(sa.UnicodeText)
    activitylocations = sa.orm.relationship("ActivityLocation",
            cascade="all, delete-orphan",
            backref="locations")

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityLocation(db.Model):
    __tablename__ = 'activitylocation'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(sa.Integer,
            sa.ForeignKey('activity.id'),
            nullable=False)
    location_id = sa.Column(sa.Integer,
            sa.ForeignKey('location.id'),
            nullable=False)

    def as_dict(self):
       ret_data = {}
       ret_data.update({c.name: getattr(self, c.name) for c in self.__table__.columns})
       ret_data.update({key: getattr(self, key).as_dict() for key in self.__mapper__.relationships.keys()})
       return ret_data

class Organisation(db.Model):
    __tablename__ = 'organisation'
    id = sa.Column(sa.Integer,
                            primary_key=True)
    code = sa.Column(sa.UnicodeText) # eventually rename to iati_code
    budget_code = sa.Column(sa.UnicodeText)
    name = sa.Column(sa.UnicodeText)
    acronym = sa.Column(sa.UnicodeText)
    _type = sa.Column(sa.UnicodeText)
    activityorganisations = sa.orm.relationship("ActivityOrganisation",
            cascade="all, delete-orphan",
            backref="organisation")
    userorganisations = sa.orm.relationship("UserOrganisation",
            cascade="all, delete-orphan",
            backref="organisation")
    organisationresponses = sa.orm.relationship("OrganisationResponse",
            cascade="all, delete-orphan",
            backref="organisation")

    @hybrid_property
    def responses_fys(self):
        return dict(map(lambda o: (o.fyfq, o.response_id), self.organisationresponses))

    @hybrid_property
    def activities_count(self):
        return len(self.activities_as_reporting_org) #.count()

    @activities_count.expression
    def activities_count(cls):
        return (select([func.count(Activity.id)]).
                where(Activity.reporting_org_id == cls.id).
                label("activities_count")
                )

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityOrganisation(db.Model):
    __tablename__ = 'activityorganisation'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(sa.Integer,
            sa.ForeignKey('activity.id'),
            nullable=False)
    organisation_id = sa.Column(sa.Integer,
            sa.ForeignKey('organisation.id'),
            nullable=False)
    role = sa.Column(sa.Integer,
            nullable=False)
    percentage = sa.Column(sa.Float,
            default=100.00)
    __table_args__ = (sa.UniqueConstraint('activity_id','organisation_id', 'role'),)

    def as_dict(self):
       ret_data = {}
       ret_data.update({c.name: getattr(self, c.name) for c in self.__table__.columns})
       ret_data.update({key: getattr(self, key).as_dict() for key in self.__mapper__.relationships.keys()})
       return ret_data

class Codelist(db.Model):
    __tablename__ = 'codelist'
    code = sa.Column(sa.UnicodeText, primary_key=True) # should be a slug
    name = sa.Column(sa.UnicodeText)
    __table_args__ = (sa.UniqueConstraint('code',),)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class CodelistCode(db.Model):
    __tablename__ = 'codelistcode'
    id = sa.Column(sa.Integer, primary_key=True)
    code = sa.Column(sa.UnicodeText)
    name = sa.Column(sa.UnicodeText)
    codelist_code = sa.Column(sa.Integer,
            sa.ForeignKey('codelist.code'),
            nullable=False)
    codelist = sa.orm.relationship("Codelist")
    __table_args__ = (sa.UniqueConstraint('code','codelist_code'),)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityCodelistCode(db.Model):
    __tablename__ = 'activitycodelistcode'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(sa.Integer,
            sa.ForeignKey('activity.id'),
            nullable=False)
    codelist_code_id = sa.Column(sa.Integer,
            sa.ForeignKey('codelistcode.id'),
            nullable=False)
    codelist_code = sa.orm.relationship("CodelistCode")
    percentage = sa.Column(sa.Float,
            default=100.00)
    __table_args__ = (sa.UniqueConstraint('activity_id','codelist_code_id'),)

    def as_dict(self):
       ret_data = {}
       ret_data.update({c.name: getattr(self, c.name) for c in self.__table__.columns})
       ret_data.update({key: getattr(self, key).as_dict() for key in self.__mapper__.relationships.keys()})
       return ret_data

class ActivityFinancesCodelistCode(db.Model):
    __tablename__ = 'activityfinancescodelistcode'
    id = sa.Column(sa.Integer, primary_key=True)
    activityfinance_id = sa.Column(sa.Integer,
            sa.ForeignKey('activityfinances.id'),
            nullable=False)
    codelist_id = sa.Column(sa.Integer,
            sa.ForeignKey('codelist.code'),
            nullable=False)
    codelist_code_id = sa.Column(sa.Integer,
            sa.ForeignKey('codelistcode.id'),
            nullable=False)
    codelist_code = sa.orm.relationship("CodelistCode")
    __table_args__ = (sa.UniqueConstraint('activityfinance_id','codelist_id'),)

    def as_dict(self):
       ret_data = {}
       ret_data.update({c.name: getattr(self, c.name) for c in self.__table__.columns})
       ret_data.update({key: getattr(self, key).as_dict() for key in ['codelist_code']})
       return ret_data

class Milestone(db.Model):
    __tablename__ = 'milestone'
    id = sa.Column(sa.Integer, primary_key=True)
    milestone_order = sa.Column(sa.Integer)
    name = sa.Column(sa.UnicodeText)
    domestic_external = sa.Column(sa.UnicodeText)
    activitymilestones = sa.orm.relationship("ActivityMilestone",
            cascade="all, delete-orphan",
            backref="milestone")

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityMilestone(db.Model):
    __tablename__ = 'activitymilestone'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(
            act_ForeignKey('activity.id'),
            nullable=False,
            index=True)
    milestone_id = sa.Column(
            act_ForeignKey('milestone.id'),
            nullable=False,
            index=True)
    achieved = sa.Column(sa.Boolean)
    notes = sa.Column(sa.UnicodeText)

    __table_args__ = (sa.UniqueConstraint('activity_id','milestone_id'),)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityCounterpartFunding(db.Model):
    __tablename__ = 'activitycounterpartfunding'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(sa.Integer,
            sa.ForeignKey('activity.id'),
            nullable=False,
            index=True)
    required_value = sa.Column(sa.Float(precision=2))
    required_date = sa.Column(sa.Date)
    budgeted = sa.Column(sa.Boolean, default=False)
    allotted = sa.Column(sa.Boolean, default=False)
    disbursed = sa.Column(sa.Boolean, default=False)

    __table_args__ = (sa.UniqueConstraint('activity_id','required_date'),)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityResult(db.Model):
    __tablename__ = 'activityresult'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(
            act_ForeignKey('activity.id'),
            nullable=False,
            index=True)
    result_title = sa.Column(sa.UnicodeText)
    result_description = sa.Column(sa.UnicodeText)
    result_type = sa.Column(sa.Integer)
    source = sa.Column(sa.Integer)
    indicators = cascade_relationship(
        "ActivityResultIndicator",
        backref="result")

    indicator_periods = sa.orm.relationship("ActivityResultIndicatorPeriod",
        secondary="join(ActivityResultIndicator, ActivityResultIndicatorPeriod, ActivityResultIndicator.id == ActivityResultIndicatorPeriod.indicator_id)",
        primaryjoin="ActivityResult.id == ActivityResultIndicator.result_id",
        secondaryjoin="ActivityResultIndicator.id == ActivityResultIndicatorPeriod.indicator_id",
        viewonly = True
        )

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityResultIndicator(db.Model):
    __tablename__ = 'activityresultindicator'
    id = sa.Column(sa.Integer, primary_key=True)
    result_id = sa.Column(
            act_ForeignKey('activityresult.id'),
            nullable=False,
            index=True)
    indicator_title = sa.Column(sa.UnicodeText)
    indicator_description = sa.Column(sa.UnicodeText)
    baseline_year = sa.Column(sa.Date)
    baseline_value = sa.Column(sa.UnicodeText)
    measurement_type = sa.Column(sa.UnicodeText)
    measurement_unit_type = sa.Column(sa.UnicodeText)
    baseline_comment = sa.Column(sa.UnicodeText)
    periods = cascade_relationship(
        "ActivityResultIndicatorPeriod",
        backref="result_indicator")

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ActivityResultIndicatorPeriod(db.Model):
    __tablename__ = 'activityresultindicatorperiod'
    id = sa.Column(sa.Integer, primary_key=True)
    indicator_id = sa.Column(
            act_ForeignKey('activityresultindicator.id'),
            nullable=False,
            index=True)
    period_start = sa.Column(sa.Date)
    period_end = sa.Column(sa.Date)
    target_value = sa.Column(sa.UnicodeText)
    target_comment = sa.Column(sa.UnicodeText)
    actual_value = sa.Column(sa.UnicodeText)
    actual_comment = sa.Column(sa.UnicodeText)
    status = sa.Column(sa.Integer, nullable=False, default=3)

    @hybrid_property
    def open(self):
        if self.status == 4: return False
        return self.period_start < datetime.datetime.utcnow().date()

    @hybrid_property
    def percent_complete(self):
        if self.actual_value == None:
            return None
        try:
            return int(round((float(self.actual_value) / float(self.target_value))*100.0))
        except ZeroDivisionError:
            return None
        except ValueError:
            return None

    @hybrid_property
    def percent_complete_category(self):
        if self.percent_complete is not None:
            if self.percent_complete >= 80:
                return "success"
            elif self.percent_complete >= 40:
                return "warning"
            else:
                return "danger"
        return None

    def as_dict(self):
        ret_data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        ret_data.update({key: getattr(self, key) for key in ['open']})
        return ret_data


class ActivityLog(db.Model):
    __tablename__ = 'activitylog'
    id = sa.Column(sa.Integer, primary_key=True)
    activity_id = sa.Column(
            act_ForeignKey('activity.id'),
            nullable=False,
            index=True)
    user_id = sa.Column(
            act_ForeignKey('maediuser.id'),
            nullable=False,
            index=True)
    mode = sa.Column(sa.UnicodeText)
    @hybrid_property
    def mode_text(self):
        mode_texts = {
            "add": "added",
            "update": "updated",
            "delete": "deleted"
        }
        return mode_texts.get(self.mode, self.mode)
    target = sa.Column(sa.UnicodeText)
    @hybrid_property
    def target_text(self):
        target_texts = {
            "ActivityLocation": "location",
            "ActivityForwardSpend": "forward spending data",
            "ActivityFinances": "financial data",
            "ActivityFinancesCodelistCode": "financial data classification",
            "Activity": "activity"
        }
        return target_texts.get(self.target, self.target)
    target_id = sa.Column(sa.Integer)
    old_value = sa.Column(sa.UnicodeText)
    value = sa.Column(sa.UnicodeText)
    log_date = sa.Column(sa.DateTime,
        nullable=False,
        default=datetime.datetime.utcnow)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class User(db.Model):
    __tablename__ = 'maediuser'
    id = sa.Column(sa.Integer, primary_key=True)
    username = sa.Column(sa.UnicodeText, nullable=False)
    name = sa.Column(sa.UnicodeText)
    email_address = sa.Column(sa.UnicodeText)
    reset_password_key = sa.Column(sa.UnicodeText)
    reset_password_expiry = sa.Column(sa.DateTime)
    pw_hash = db.Column(sa.String(255))
    organisation = sa.Column(sa.UnicodeText)
    administrator = sa.Column(sa.Boolean,
                               default=False)
    recipient_country_code = sa.Column(
            act_ForeignKey('country.code'),
            nullable=False,
            index=True) # we set a default country code for each user
    recipient_country = sa.orm.relationship("Country")
    permissions = db.relationship("UserPermission",
                    cascade="all, delete-orphan",
                    passive_deletes=True)
    organisations = db.relationship("UserOrganisation",
                    cascade="all, delete-orphan",
                    passive_deletes=True)
    userroles = db.relationship("UserRole",
                    cascade="all, delete-orphan",
                    passive_deletes=True,
                    backref="user")
    @hybrid_property
    def roles_list(self):
        return list(map(lambda r: r.role.slug, self.userroles))

    activity_logs = cascade_relationship(
        "ActivityLog",
        backref="user")
    __table_args__ = (sa.UniqueConstraint('username',),)

    def setup(self,
                 username,
                 password,
                 name,
                 email_address=None,
                 organisation=None,
                 recipient_country_code=None,
                 administrator=False,
                 id=None):
        self.username = username
        self.pw_hash = generate_password_hash(password)
        self.name = name
        self.email_address = email_address
        self.organisation = organisation
        self.recipient_country_code = recipient_country_code
        self.administrator = administrator
        if id is not None:
            self.id = id

    def check_password(self, password):
        return check_password_hash(self.pw_hash, password)

    def is_active(self):
        return True

    def get_id(self):
        return self.id

    def is_anonymous(self):
        return False

    def is_authenticated(self):
        return True

    @hybrid_property
    def permissions_list(self):
        if not self.permissions:
            return {'organisations': {}}
        permissions = dict(map(lambda p: (p.permission_name, p.permission_value), self.permissions))
        permissions["organisations"] = collections.defaultdict(list)
        for op in self.organisations:
            permissions["organisations"][op.organisation_id].append(op.permission_value)
        return permissions

    @hybrid_property
    def permissions_dict(self):
        if not self.permissions:
            return {'organisations': {}}
        permissions = dict(map(lambda p: (p.permission_name, p.permission_value), self.permissions))
        permissions["organisations"] = dict(map(lambda op: (op.organisation_id, op.as_dict()), self.organisations))
        return permissions

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class UserPermission(db.Model):
    __tablename__ = 'userpermission'
    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.Integer,
                        sa.ForeignKey('maediuser.id',
                        ondelete='CASCADE'))
    permission_name = sa.Column(sa.UnicodeText)
    permission_value = sa.Column(sa.UnicodeText)

    def setup(self,
             user_id,
             permission_name=None,
             id=None):
        self.user_id = user_id
        self.permission_name = permission_name
        self.permission_value = permission_value
        if id is not None:
            self.id = id

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Role(db.Model):
    __tablename__ = 'role'
    id = sa.Column(sa.Integer, primary_key=True)
    slug = sa.Column(sa.UnicodeText, nullable=False,
        unique=True)
    name = sa.Column(sa.UnicodeText, nullable=False)
    userroles = db.relationship("UserRole",
                    cascade="all, delete-orphan",
                    passive_deletes=True,
                    backref="role")
    rolepermissions = db.relationship("RolePermission",
                    cascade="all, delete-orphan",
                    passive_deletes=True,
                    backref="role")

    def setup(self,
             name,
             id=None):
        self.name = name
        if id is not None:
            self.id = id

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class UserRole(db.Model):
    __tablename__ = 'userrole'
    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.Integer,
                        sa.ForeignKey('maediuser.id',
                        ondelete='CASCADE'), nullable=False)
    role_id = sa.Column(sa.Integer,
                        sa.ForeignKey('role.id',
                        ondelete='CASCADE'), nullable=False)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    __table_args__ = (
        db.UniqueConstraint('user_id', 'role_id', name='user_id_role_id'),
    )


class Permission(db.Model):
    __tablename__ = 'permission'
    id = sa.Column(sa.Integer, primary_key=True)
    slug = sa.Column(sa.UnicodeText)
    name = sa.Column(sa.UnicodeText)
    description = sa.Column(sa.UnicodeText)
    rolepermissions = db.relationship("RolePermission",
                    cascade="all, delete-orphan",
                    passive_deletes=True,
                    backref="permission")

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class RolePermission(db.Model):
    __tablename__ = 'permissionrole'
    id = sa.Column(sa.Integer, primary_key=True)
    role_id = sa.Column(sa.Integer,
                        sa.ForeignKey('role.id',
                        ondelete='CASCADE'), nullable=False)
    permission_id = sa.Column(sa.Integer,
                        sa.ForeignKey('permission.id',
                        ondelete='CASCADE'), nullable=False)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    __table_args__ = (
        db.UniqueConstraint('role_id', 'permission_id', name='role_id_permission_id'),
    )


class OrganisationResponse(db.Model):
    __tablename__ = 'organisationresponse'
    id = sa.Column(sa.Integer, primary_key=True)
    response_id = sa.Column(sa.Integer,
                        sa.ForeignKey('response.id',
                        ondelete='CASCADE'), nullable=False)
    organisation_id = sa.Column(sa.Integer,
                        sa.ForeignKey('organisation.id',
                        ondelete='CASCADE'), nullable=False)
    modified = sa.Column(sa.DateTime,
        default=datetime.datetime.utcnow, nullable=False)
    fyfq = sa.Column(sa.UnicodeText, nullable=False)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    __table_args__ = (
        db.UniqueConstraint('organisation_id', 'fyfq', name='unique_fyfq_organisation_id'),
    )


class Response(db.Model):
    __tablename__ = 'response'
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.UnicodeText, nullable=False)
    icon = sa.Column(sa.UnicodeText, nullable=False)
    organisationresponse = sa.orm.relationship("OrganisationResponse",
            cascade="all, delete-orphan",
            backref="response")

    def setup(self,
             name,
             id=None):
        self.name = name
        if id is not None:
            self.id = id

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class UserOrganisation(db.Model):
    __tablename__ = 'userorganisation'
    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.Integer,
                        sa.ForeignKey('maediuser.id',
                        ondelete='CASCADE'))
    permission_name = sa.Column(sa.UnicodeText)
    permission_value = sa.Column(sa.UnicodeText)
    organisation_id = sa.Column(sa.Integer,
            sa.ForeignKey('organisation.id'),
            nullable=False)

    def as_dict(self):
       return {c.name: getattr(self, c.name) for c in self.__table__.columns}
