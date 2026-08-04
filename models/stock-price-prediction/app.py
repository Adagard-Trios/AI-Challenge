"""
Stock Price Prediction - Streamlit App
Interactive web app to visualize stock price predictions and test the trained LSTM model.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import os
import pickle
from datetime import datetime, timedelta
import yfinance as yf

# Page configuration
st.set_page_config(
    page_title="Stock Price Prediction",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

def get_latest_artifacts_dir():
    """Find the latest artifacts directory"""
    artifacts_base = "Artifacts"
    if not os.path.exists(artifacts_base):
        return None

    dirs = [d for d in os.listdir(artifacts_base) if os.path.isdir(os.path.join(artifacts_base, d))]
    if not dirs:
        return None

    # Sort by timestamp in directory name
    dirs.sort(reverse=True)
    return os.path.join(artifacts_base, dirs[0])

def load_model_and_scaler(artifacts_dir):
    """Load the trained model and scaler from artifacts"""
    try:
        # Load scaler
        scaler_path = os.path.join(artifacts_dir, "data_transformation", "transformed_object", "preprocessing.pkl")
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)

        # Load model
        model_path = os.path.join(artifacts_dir, "model_trainer", "trained_model", "model.pkl")
        with open(model_path, 'rb') as f:
            model = pickle.load(f)

        return model, scaler
    except Exception as e:
        st.error(f"Error loading model: {e}")
        return None, None

def load_test_data(artifacts_dir):
    """Load test data from artifacts"""
    try:
        test_path = os.path.join(artifacts_dir, "data_transformation", "transformed", "test.npy")
        with open(test_path, 'rb') as f:
            test_data = pickle.load(f)
        return test_data
    except Exception as e:
        st.error(f"Error loading test data: {e}")
        return None

def load_historical_data(artifacts_dir):
    """Load historical stock data from feature store"""
    try:
        # Try to find the CSV in ingested folder
        csv_path = os.path.join(artifacts_dir, "data_ingestion", "ingested", "train.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            return df

        # Also load test data
        test_csv_path = os.path.join(artifacts_dir, "data_ingestion", "ingested", "test.csv")
        if os.path.exists(test_csv_path):
            test_df = pd.read_csv(test_csv_path)
            if os.path.exists(csv_path):
                train_df = pd.read_csv(csv_path)
                return pd.concat([train_df, test_df], ignore_index=True)
            return test_df
        return None
    except Exception as e:
        st.error(f"Error loading historical data: {e}")
        return None

def create_price_chart(df):
    """Create interactive price chart"""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03,
                        row_heights=[0.7, 0.3],
                        subplot_titles=('Stock Price', 'Volume'))

    # Price chart
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Close'], mode='lines',
                   name='Close Price', line=dict(color='#1E88E5', width=2)),
        row=1, col=1
    )

    # Add high/low range
    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['High'], mode='lines',
                   name='High', line=dict(color='#4CAF50', width=1, dash='dot')),
        row=1, col=1
    )

    fig.add_trace(
        go.Scatter(x=df['Date'], y=df['Low'], mode='lines',
                   name='Low', line=dict(color='#F44336', width=1, dash='dot')),
        row=1, col=1
    )

    # Volume chart
    if 'Volume' in df.columns:
        colors = ['#4CAF50' if df['Close'].iloc[i] >= df['Open'].iloc[i] else '#F44336'
                  for i in range(len(df))]
        fig.add_trace(
            go.Bar(x=df['Date'], y=df['Volume'], name='Volume', marker_color=colors),
            row=2, col=1
        )

    fig.update_layout(
        height=600,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template='plotly_white',
        xaxis_rangeslider_visible=False
    )

    fig.update_yaxes(title_text="Price (LKR)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig

def create_prediction_chart(y_actual, y_pred, dates=None):
    """Create actual vs predicted chart"""
    fig = go.Figure()

    x_axis = dates if dates is not None else list(range(len(y_actual)))

    fig.add_trace(
        go.Scatter(x=x_axis, y=y_actual, mode='lines',
                   name='Actual Price', line=dict(color='#1E88E5', width=2))
    )

    fig.add_trace(
        go.Scatter(x=x_axis, y=y_pred, mode='lines',
                   name='Predicted Price', line=dict(color='#FF6B6B', width=2, dash='dash'))
    )

    fig.update_layout(
        title='Actual vs Predicted Stock Price',
        xaxis_title='Time',
        yaxis_title='Price (LKR)',
        height=500,
        template='plotly_white',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    return fig

def calculate_metrics(y_actual, y_pred):
    """Calculate regression metrics"""
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score, mean_absolute_percentage_error

    rmse = np.sqrt(mean_squared_error(y_actual, y_pred))
    mae = mean_absolute_error(y_actual, y_pred)
    r2 = r2_score(y_actual, y_pred)
    mape = mean_absolute_percentage_error(y_actual, y_pred)

    return rmse, mae, r2, mape

def main():
    # Header
    st.markdown('<p class="main-header">📈 Stock Price Prediction</p>', unsafe_allow_html=True)
    st.markdown("---")

    # Sidebar
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/000000/stocks.png", width=80)
        st.title("Settings")

        # Find latest artifacts
        artifacts_dir = get_latest_artifacts_dir()

        if artifacts_dir:
            st.success(f"✅ Model found: {os.path.basename(artifacts_dir)}")
        else:
            st.error("❌ No trained model found. Please run main.py first.")
            return

        st.markdown("---")

        # Stock info
        st.subheader("📊 Stock Info")
        st.info("**Ticker:** COMB-N0000.CM\n\n**Exchange:** Colombo Stock Exchange\n\n**Type:** LSTM Prediction")

    # Main content
    tab1, tab2, tab3 = st.tabs(["📊 Historical Data", "🎯 Predictions", "📈 Model Performance"])

    with tab1:
        st.subheader("Historical Stock Price Data")

        # Load historical data
        df = load_historical_data(artifacts_dir)

        if df is not None:
            # Display chart
            fig = create_price_chart(df)
            st.plotly_chart(fig, use_container_width=True)

            # Statistics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Current Price", f"LKR {df['Close'].iloc[-1]:.2f}")
            with col2:
                st.metric("52-Week High", f"LKR {df['High'].max():.2f}")
            with col3:
                st.metric("52-Week Low", f"LKR {df['Low'].min():.2f}")
            with col4:
                avg_volume = df['Volume'].mean() if 'Volume' in df.columns else 0
                st.metric("Avg Volume", f"{avg_volume:,.0f}")

            # Data table
            with st.expander("📋 View Raw Data"):
                st.dataframe(df.tail(50), use_container_width=True)
        else:
            st.warning("No historical data available.")

    with tab2:
        st.subheader("Model Predictions")

        # Load model and data
        model, scaler = load_model_and_scaler(artifacts_dir)
        test_data = load_test_data(artifacts_dir)

        if model is not None and scaler is not None and test_data is not None:
            X_test, y_test = test_data

            # Make predictions
            with st.spinner("Making predictions..."):
                y_pred_scaled = model.predict(X_test, verbose=0)

                # Inverse transform
                y_pred = scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).flatten()
                y_actual = scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()

            # Create prediction chart
            fig = create_prediction_chart(y_actual, y_pred)
            st.plotly_chart(fig, use_container_width=True)

            # Calculate and display metrics
            rmse, mae, r2, mape = calculate_metrics(y_actual, y_pred)

            st.markdown("### 📊 Prediction Metrics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("RMSE", f"{rmse:.2f}")
            with col2:
                st.metric("MAE", f"{mae:.2f}")
            with col3:
                st.metric("R² Score", f"{r2:.4f}")
            with col4:
                st.metric("MAPE", f"{mape:.2%}")

            # Prediction samples
            with st.expander("🔍 View Prediction Samples"):
                sample_df = pd.DataFrame({
                    'Actual Price': y_actual[:20],
                    'Predicted Price': y_pred[:20],
                    'Difference': y_actual[:20] - y_pred[:20]
                })
                st.dataframe(sample_df, use_container_width=True)
        else:
            st.warning("Model or test data not available. Please train the model first by running main.py")

    with tab3:
        st.subheader("Model Performance Analysis")

        if model is not None and scaler is not None and test_data is not None:
            X_test, y_test = test_data

            # Make predictions
            y_pred_scaled = model.predict(X_test, verbose=0)
            y_pred = scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).flatten()
            y_actual = scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()

            # Residual analysis
            residuals = y_actual - y_pred

            col1, col2 = st.columns(2)

            with col1:
                # Residual distribution
                fig_residual = px.histogram(
                    x=residuals,
                    nbins=50,
                    title="Residual Distribution",
                    labels={'x': 'Residual (Actual - Predicted)', 'y': 'Count'}
                )
                fig_residual.update_layout(height=400, template='plotly_white')
                st.plotly_chart(fig_residual, use_container_width=True)

            with col2:
                # Scatter plot
                fig_scatter = px.scatter(
                    x=y_actual,
                    y=y_pred,
                    title="Actual vs Predicted Scatter",
                    labels={'x': 'Actual Price', 'y': 'Predicted Price'}
                )
                # Add perfect prediction line
                min_val = min(y_actual.min(), y_pred.min())
                max_val = max(y_actual.max(), y_pred.max())
                fig_scatter.add_trace(
                    go.Scatter(x=[min_val, max_val], y=[min_val, max_val],
                              mode='lines', name='Perfect Prediction',
                              line=dict(color='red', dash='dash'))
                )
                fig_scatter.update_layout(height=400, template='plotly_white')
                st.plotly_chart(fig_scatter, use_container_width=True)

            # Error statistics
            st.markdown("### 📉 Error Statistics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Mean Error", f"{residuals.mean():.2f}")
            with col2:
                st.metric("Std Dev", f"{residuals.std():.2f}")
            with col3:
                st.metric("Max Overestimate", f"{residuals.min():.2f}")
            with col4:
                st.metric("Max Underestimate", f"{residuals.max():.2f}")
        else:
            st.warning("Model not available for performance analysis.")

    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center; color: #666;'>
            <p>Stock Price Prediction using Bidirectional LSTM | Sri Lanka AI Challenge 2026 Project</p>
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
