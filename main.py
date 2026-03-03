##import section
import streamlit as st

##setting the page up
st.set_page_config(layout="wide")

##setting simple sidebar (will need change)
with st.sidebar:
    spaceLeft, mainContent, spaceRight = st.columns([0.5, 2, 0.5])

    with mainContent:
        st.write("File Upload")
        st.button("Upload", width=84)
        
        st.write("Workflow")
        st.button("Reset Session")
        st.button("Undo Last Step")

        st.write("Logs")
        st.space(size=1)
        st.write("Here must be logs...")
        st.space(size=1)
        st.write("View full log")

##setting tabs to scroll through (will need change)
overviewTab, cleaningStudioTab, visualizationTab, exportReportTab =\
      st.tabs(["Overview", "Cleaning Studio", "Visualization", "Export & Report"],\
              width = 1490,\
              default = "Overview")

##setting overview tab (will need change)
with overviewTab:
    st.header("Dataset Overview")
    st.write("Here you can explore uploaded dataset metrics")

    st.space(size=1)

    ##setting columns inside of the overview tab
    rowsColumn, columnsColumn, numericColumn, categoricalColumn, datetimeColumn = st.columns([2, 2, 2, 2, 2])

    with rowsColumn:
        st.header("Number of")
        st.write("Rows")

    with columnsColumn:
        st.header("Number of")
        st.write("Columns")

    with numericColumn:
        st.header("Number of")
        st.write("Numeric Columns")

    with categoricalColumn:
        st.header("Number of")
        st.write("Categorical Columns")

    with datetimeColumn:
        st.header("Number of")
        st.write("Datetime Columns")
    
    st.space(size=15)
    
    st.write("Total columns: will be known...")

    st.space(size=10)

    st.header("Data Profiling")

    st.space(size=50)

    ##setting separate column field to create layout inside of overview section
    datatypesColumn, mvDPColumn = st. columns([4, 4])
    with datatypesColumn:
        st.header("Data Types")
        st.write("here will be info")
    
    with mvDPColumn:
        st.header("Missing Values")
        st.write("here will be info")
        st.space(size=50)

    with mvDPColumn:
        st.header("Duplicates")
        st.write("here will be info")
        st.button("Remove Duplicates")

##setting overview tab (will need change)
with cleaningStudioTab:
    st.header("Cleaning Studio")
    st.write("Clean, transform, and prepare your dataset with different options")

    mainColumn, metricsColumn = st. columns([4, 4])
    
    ##main columns setup (will need change)
    with mainColumn:

        with st.expander("Missing values"):
            st.header("Select columns")
            st.write("here column names")

            st.space(size=30)

            st.header("Action")
            st.write("number of missing values")
            st.button("Apply transformation")

            st.space(size=10)

            st.write("Preview: rows affected")
        
        with st.expander("Duplicate Handling"):
            st.header("Duplicate Handling")
        
        with st.expander("Data type conversion"):
            st.header("Data type conversion")
        
        with st.expander("Categorical cleaning"):
            st.header("Categorical cleaning")
        
        with st.expander("Outlier handling"):
            st.header("Outlier handling")
        
        with st.expander("Scaling"):
            st.header("Scaling")
        
        with st.expander("Column operations"):
            st.header("Column operations")
        
        with st.expander("Data validation"):
            st.header("Data validation")
    
    with metricsColumn:
        st.header("Transformation preview")
        st.write("Rows")
        st.write("Columns")
        st.write("Rows affected")
        st.write("Columns affected")
    
    with metricsColumn:
        st.header("Transformation preview")
        st.write("Information loading...")
        st.write("Information loading...")
        st.write("Information loading...")
        st.write("Information loading...")
        
        ##setting up button columns (will need change)
        buttonUndoCleaningColumn, buttonResetCleaningColumn = st.columns([2, 2])
        with buttonUndoCleaningColumn:
            st.button("Undo Last Step")
        
        with buttonResetCleaningColumn:
            st.button("Reset All")

##setting overview tab (will need change)
with visualizationTab:
    st.header("here will be visualization")

##setting overview tab (will need change)
with exportReportTab:
    st.header("here will be export and report")