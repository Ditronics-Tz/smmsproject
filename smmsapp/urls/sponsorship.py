from django.urls import path

from smmsapp.views.sponsorship import (
    CloseSponsorFundView, FundContributionView, SponsorFundDetailView,
    SponsorFundsView, SponsorshipAllocationCreateView,
    SponsorshipAllocationDeactivateView, SponsorshipAllocationBulkView,
    SponsorFundDashboardView, SponsorFundReportView,
)

urlpatterns = [
    path('funds', SponsorFundsView.as_view(), name='sponsorship-funds'),
    path('funds/<int:fund_id>', SponsorFundDetailView.as_view(), name='sponsorship-fund-detail'),
    path('funds/<int:fund_id>/contribute', FundContributionView.as_view(), name='sponsorship-fund-contribute'),
    path('funds/<int:fund_id>/close', CloseSponsorFundView.as_view(), name='sponsorship-fund-close'),
    path('funds/<int:fund_id>/dashboard', SponsorFundDashboardView.as_view(), name='sponsorship-fund-dashboard'),
    path('funds/<int:fund_id>/report', SponsorFundReportView.as_view(), name='sponsorship-fund-report'),
    path('allocations', SponsorshipAllocationCreateView.as_view(), name='sponsorship-allocations'),
    path('allocations/bulk', SponsorshipAllocationBulkView.as_view(), name='sponsorship-allocations-bulk'),
    path('allocations/<int:allocation_id>/deactivate', SponsorshipAllocationDeactivateView.as_view(), name='sponsorship-allocation-deactivate'),
]
