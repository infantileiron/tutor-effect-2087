-- 002: 联合检验包（Holm 多重比较校正）。新库由 metadata.create_all 自动建表；既有库人工执行本文件。
CREATE TABLE IF NOT EXISTS joint_packages (
    id SERIAL PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL,
    plan_snapshots JSON NOT NULL,
    alpha FLOAT NOT NULL,
    result JSON,
    error TEXT NOT NULL DEFAULT '',
    conclusion TEXT NOT NULL DEFAULT '',
    published BOOLEAN NOT NULL DEFAULT FALSE,
    published_at VARCHAR(40),
    created_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS joint_package_items (
    id SERIAL PRIMARY KEY,
    package_id INTEGER NOT NULL REFERENCES joint_packages(id),
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    plan_title VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL,
    student_snapshot JSON NOT NULL,
    result JSON,
    raw_p_value FLOAT,
    holm_adjusted_p FLOAT,
    holm_rank INTEGER,
    holm_significant BOOLEAN,
    error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at VARCHAR(40) NOT NULL,
    CONSTRAINT uq_package_plan UNIQUE (package_id, plan_id)
);
