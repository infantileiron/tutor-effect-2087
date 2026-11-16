ROLES=('admin','analyst','viewer')
REPORT_STATUSES=('queued','running','completed','failed')
# 联合检验包生命周期：待计算 → 计算中 → 待发布 → 已发布；失败后沿原包重试恢复
PACKAGE_STATUSES=('queued','running','completed','failed','published')
PACKAGE_ITEM_STATUSES=('queued','running','completed','failed')
GROUPS=('control','intervention')
# Holm 逐步检验的族系误报率
FAMILY_ALPHA=0.05
