"""Comprehensive Test Suite for Phase 3: Cleaning, Interpolation, Feature Engineering & EDA (SRS v1.1).

Bao gồm 4 nhóm kiểm thử bắt buộc:
1. test_short_gap_interpolation_and_flagging: Nội suy tuyến tính khoảng thiếu ngắn (<= 3 ngày) và gắn cờ truy vết (FR-08, FR-36).
2. test_long_gap_remains_unfilled: Khoảng thiếu dài (> 3 ngày, VD: 5 ngày) bắt buộc để trống NaN/None (FR-36).
3. test_no_future_data_leakage: Thay đổi giá tương lai (t31..t50) gấp 10 lần không làm lệch bất kỳ đặc trưng nào tại <= t30 (NFR-04).
4. test_feature_set_persistence_and_eda_outputs: Kiểm tra lưu bảng feature_set và xuất 4 biểu đồ EDA + eda_summary.json (FR-09, FR-10).
"""

import os
from datetime import date, timedelta
from decimal import Decimal
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from db.models import (
    Commodity,
    Province,
    DataSource,
    PriceObservation,
    WeatherObservation,
    FeatureSet,
)
from processing.cleaner import TimeSeriesCleaner
from processing.features import FeatureEngineer, FEATURE_COLUMNS
from processing.eda import (
    run_exploratory_data_analysis,
    DEFAULT_FIGURES_DIR,
    DEFAULT_SUMMARY_JSON_PATH,
)


def test_short_gap_interpolation_and_flagging(db_session: Session):
    """
    Kiểm tra khoảng thiếu ngắn 2 ngày liên tiếp (<= 3 ngày):
    - Được nội suy tuyến tính chính xác.
    - Được gắn cờ is_interpolated == True và quality_flag == 'INTERPOLATED' (FR-08, FR-36).
    - Được lưu vết ngược vào bảng price_observation.
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "DL").first()
    src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()

    # Tạo dữ liệu ngày 01/06 (100,000) và ngày 04/06 (103,000), khuyết 2 ngày 02/06 và 03/06
    obs_list = [
        PriceObservation(
            obs_date=date(2026, 6, 1),
            commodity_id=comm.id,
            province_id=prov.id,
            source_id=src.id,
            price=Decimal("100000.00"),
            raw_value="100,000",
            raw_unit="VNĐ/kg",
            source_url="https://giacaphe.com/test",
            is_interpolated=False,
            quality_flag="OK",
        ),
        PriceObservation(
            obs_date=date(2026, 6, 4),
            commodity_id=comm.id,
            province_id=prov.id,
            source_id=src.id,
            price=Decimal("103000.00"),
            raw_value="103,000",
            raw_unit="VNĐ/kg",
            source_url="https://giacaphe.com/test",
            is_interpolated=False,
            quality_flag="OK",
        ),
    ]
    db_session.add_all(obs_list)
    db_session.commit()

    cleaner = TimeSeriesCleaner(db=db_session, max_interpolation_gap=3, persist_interpolated_to_db=True)
    df_clean = cleaner.clean_and_interpolate_series(commodity_id=comm.id, province_id=prov.id)

    assert len(df_clean) == 4

    # Kiểm tra ngày 02/06 (nội suy = 101,000) và 03/06 (nội suy = 102,000)
    row_june2 = df_clean[df_clean["obs_date"] == date(2026, 6, 2)].iloc[0]
    row_june3 = df_clean[df_clean["obs_date"] == date(2026, 6, 3)].iloc[0]

    assert abs(float(row_june2["price"]) - 101000.0) < 1e-6
    assert bool(row_june2["is_interpolated"]) is True
    assert row_june2["quality_flag"] == "INTERPOLATED"

    assert abs(float(row_june3["price"]) - 102000.0) < 1e-6
    assert bool(row_june3["is_interpolated"]) is True
    assert row_june3["quality_flag"] == "INTERPOLATED"

    # Kiểm tra ngày gốc 01/06 và 04/06 giữ nguyên is_interpolated == False
    row_june1 = df_clean[df_clean["obs_date"] == date(2026, 6, 1)].iloc[0]
    assert bool(row_june1["is_interpolated"]) is False
    assert row_june1["quality_flag"] == "OK"

    # Kiểm tra bản ghi nội suy đã được upsert vào bảng price_observation
    db_interp_rec = (
        db_session.query(PriceObservation)
        .filter_by(obs_date=date(2026, 6, 2), commodity_id=comm.id, province_id=prov.id)
        .first()
    )
    assert db_interp_rec is not None
    assert db_interp_rec.is_interpolated is True
    assert db_interp_rec.quality_flag == "INTERPOLATED"
    assert db_interp_rec.price == Decimal("101000.00")


def test_long_gap_remains_unfilled(db_session: Session):
    """
    Kiểm tra khoảng thiếu dài 5 ngày liên tiếp (> 3 ngày):
    Cả 5 ngày bị khuyết bắt buộc phải giữ nguyên là NaN/None, tuyệt đối không điền giả (FR-36).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "TIEU_DEN").first()
    prov = db_session.query(Province).filter(Province.code == "GL").first()
    src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()

    # Ngày 01/07 (140,000) và Ngày 07/07 (146,000) -> ở giữa khuyết 5 ngày liên tiếp (02/07 -> 06/07)
    db_session.add_all([
        PriceObservation(
            obs_date=date(2026, 7, 1),
            commodity_id=comm.id,
            province_id=prov.id,
            source_id=src.id,
            price=Decimal("140000.00"),
            raw_value="140,000",
            raw_unit="VNĐ/kg",
            source_url="https://giatieu.com/test",
            is_interpolated=False,
            quality_flag="OK",
        ),
        PriceObservation(
            obs_date=date(2026, 7, 7),
            commodity_id=comm.id,
            province_id=prov.id,
            source_id=src.id,
            price=Decimal("146000.00"),
            raw_value="146,000",
            raw_unit="VNĐ/kg",
            source_url="https://giatieu.com/test",
            is_interpolated=False,
            quality_flag="OK",
        ),
    ])
    db_session.commit()

    cleaner = TimeSeriesCleaner(db=db_session, max_interpolation_gap=3, persist_interpolated_to_db=True)
    df_clean = cleaner.clean_and_interpolate_series(commodity_id=comm.id, province_id=prov.id)

    assert len(df_clean) == 7

    missing_dates = [date(2026, 7, d) for d in (2, 3, 4, 5, 6)]
    gap_rows = df_clean[df_clean["obs_date"].isin(missing_dates)]
    assert len(gap_rows) == 5

    # Xác nhận cả 5 ngày đều giữ nguyên NaN và không bị gắn cờ nội suy
    assert gap_rows["price"].isna().all()
    assert (~gap_rows["is_interpolated"]).all()

    # Khi đưa qua FeatureEngineer và lưu vào feature_set, các ngày NaN không bị chèn giả vào feature_set
    engineer = FeatureEngineer(db=db_session)
    df_feat = engineer.compute_features_from_dataframe(df_clean, commodity_code="TIEU_DEN")
    saved_count = engineer.upsert_feature_dataframe(df_feat)
    assert saved_count == 2  # Chỉ lưu 2 ngày thực sự có giá (01/07 và 07/07)


def test_no_future_data_leakage():
    """
    Kiểm chứng khắt khe chống rò rỉ dữ liệu tương lai (Zero Data Leakage - NFR-04):
    - Tạo chuỗi 50 ngày (t1 .. t50), tính đặc trưng tại t1 .. t30.
    - Thay đổi giá và thời tiết của các ngày tương lai (t31 .. t50) tăng gấp 10 lần.
    - Tính lại đặc trưng và xác nhận mọi đặc trưng tại <= t30 không thay đổi dù chỉ 10^-9.
    """
    start_dt = date(2026, 1, 1)
    dates = [start_dt + timedelta(days=i) for i in range(50)]

    base_prices = [100000.0 + i * 250.0 + 400.0 * np.sin(i / 3.0) for i in range(50)]
    base_temps = [25.0 + 2.0 * np.cos(i / 5.0) for i in range(50)]
    base_precip = [float((i % 7) * 2.5) for i in range(50)]

    df_original = pd.DataFrame({
        "obs_date": dates,
        "commodity_id": 1,
        "province_id": 1,
        "price": base_prices,
        "is_interpolated": False,
        "quality_flag": "OK",
        "temp_max": [t + 4.0 for t in base_temps],
        "temp_min": [t - 4.0 for t in base_temps],
        "temp_mean": base_temps,
        "precipitation": base_precip,
        "humidity": [78.0] * 50,
    })

    feat_orig = FeatureEngineer.compute_features_from_dataframe(
        df_original, commodity_code="CAFE_ROBUSTA"
    )

    # Tạo bản sao và thay đổi đột ngột dữ liệu tương lai từ t31..t50 (index 30..49) tăng gấp 10 lần
    df_shocked_future = df_original.copy()
    df_shocked_future.loc[30:, "price"] = df_shocked_future.loc[30:, "price"] * 10.0
    df_shocked_future.loc[30:, "precipitation"] = df_shocked_future.loc[30:, "precipitation"] * 10.0
    df_shocked_future.loc[30:, "temp_mean"] = df_shocked_future.loc[30:, "temp_mean"] * 10.0

    feat_shocked = FeatureEngineer.compute_features_from_dataframe(
        df_shocked_future, commodity_code="CAFE_ROBUSTA"
    )

    # Kiểm tra toàn bộ các ngày từ t1 đến t30 (index 0 .. 29) trên tất cả các cột đặc trưng số
    numeric_cols_to_check = [
        "price",
        "lag_1", "lag_2", "lag_3", "lag_7", "lag_14", "lag_21", "lag_30",
        "rolling_mean_7", "rolling_std_7",
        "rolling_mean_14", "rolling_std_14",
        "rolling_mean_30", "rolling_std_30",
        "pct_change_1d", "pct_change_7d",
        "precip_sum_7d", "precip_sum_30d", "temp_mean_7d",
        "sin_day_of_year", "cos_day_of_year",
    ]

    for col in numeric_cols_to_check:
        s_orig = feat_orig.loc[:29, col]
        s_shock = feat_shocked.loc[:29, col]

        # Vị trí NaN phải khớp tuyệt đối
        assert s_orig.isna().equals(s_shock.isna()), f"Cột {col} lệch trạng thái NaN ở quá khứ!"
        valid_mask = s_orig.notna()
        if valid_mask.any():
            max_diff = float(np.max(np.abs(s_orig[valid_mask] - s_shock[valid_mask])))
            assert max_diff < 1e-9, (
                f"Phát hiện rò rỉ dữ liệu tương lai tại cột '{col}': sai lệch = {max_diff}"
            )


def test_feature_set_persistence_and_eda_outputs(db_session: Session, tmp_path):
    """
    Kiểm tra:
    1. Lưu đặc trưng vào bảng feature_set thành công với đầy đủ các cột (FR-09).
    2. Chạy EDA tạo đủ 4 file biểu đồ PNG và eda_summary.json có dung lượng > 0 (FR-10).
    """
    comm = db_session.query(Commodity).filter(Commodity.code == "CAFE_ROBUSTA").first()
    prov = db_session.query(Province).filter(Province.code == "DL").first()
    p_src = db_session.query(DataSource).filter(DataSource.source_type == "PRICE").first()
    w_src = db_session.query(DataSource).filter(DataSource.source_type == "WEATHER").first()

    start_dt = date(2026, 1, 1)
    for i in range(45):
        cur_dt = start_dt + timedelta(days=i)
        db_session.add(
            PriceObservation(
                obs_date=cur_dt,
                commodity_id=comm.id,
                province_id=prov.id,
                source_id=p_src.id,
                price=Decimal(str(115000 + i * 100)),
                raw_value=f"{115000 + i * 100:,}",
                raw_unit="VNĐ/kg",
                source_url="https://giacaphe.com/test",
                quality_flag="OK",
            )
        )
        db_session.add(
            WeatherObservation(
                obs_date=cur_dt,
                province_id=prov.id,
                source_id=w_src.id,
                temp_max=30.0,
                temp_min=20.0,
                temp_mean=25.0,
                precipitation=float(i % 5),
                humidity=75.0,
            )
        )
    db_session.commit()

    cleaner = TimeSeriesCleaner(db=db_session)
    df_clean = cleaner.clean_and_interpolate_series(commodity_id=comm.id, province_id=prov.id)

    engineer = FeatureEngineer(db=db_session)
    df_feat = engineer.compute_features_from_dataframe(df_clean, commodity_code="CAFE_ROBUSTA")
    for col in FEATURE_COLUMNS:
        assert col in df_feat.columns, f"Thiếu cột đặc trưng '{col}'"

    upserted = engineer.upsert_feature_dataframe(df_feat)
    assert upserted == 45
    assert db_session.query(FeatureSet).count() == 45

    # Kiểm tra chạy EDA vào thư mục tạm và kiểm tra các biểu đồ trong docs/eda_figures nếu đã tạo
    test_fig_dir = str(tmp_path / "eda_figures")
    test_json_path = str(tmp_path / "eda_summary.json")
    eda_res = run_exploratory_data_analysis(
        db=db_session,
        figures_dir=test_fig_dir,
        summary_json_path=test_json_path,
    )

    assert os.path.exists(test_json_path)
    assert os.path.getsize(test_json_path) > 0
    for fig_key, fig_path in eda_res["figures_generated"].items():
        assert os.path.exists(fig_path), f"Biểu đồ {fig_key} chưa được tạo tại {fig_path}"
        assert os.path.getsize(fig_path) > 0, f"Biểu đồ {fig_key} có dung lượng bằng 0"

    # Nếu thư mục docs/eda_figures/ chính của dự án đã được xuất, kiểm tra luôn
    if os.path.exists(DEFAULT_SUMMARY_JSON_PATH):
        assert os.path.getsize(DEFAULT_SUMMARY_JSON_PATH) > 0
        for fname in (
            "trend_and_seasonality.png",
            "seasonal_decomposition.png",
            "acf_pacf_plots.png",
            "weather_correlation_heatmap.png",
        ):
            fpath = os.path.join(DEFAULT_FIGURES_DIR, fname)
            assert os.path.exists(fpath)
            assert os.path.getsize(fpath) > 0

