import QtQuick 2.6
import QtQuick.Layouts 1.0
import QtQuick.Controls 2.14
import QtQuick.Controls.Material 2.0

import org.electrum 1.0

import "controls"

Dialog {
    id: dialog

    required property QtObject finalizer
    required property Amount satoshis
    property string address
    property string message
    property alias amountLabelText: amountLabel.text
    property alias sendButtonText: sendButton.text

    title: qsTr('Confirm Transaction')

    // copy these to finalizer
    onAddressChanged: finalizer.address = address
    onSatoshisChanged: finalizer.amount = satoshis

    width: parent.width
    height: parent.height

    modal: true
    parent: Overlay.overlay
    Overlay.modal: Rectangle {
        color: "#aa000000"
    }

    GridLayout {
        id: layout
        width: parent.width
        height: parent.height
        columns: 2

        Rectangle {
            height: 1
            Layout.fillWidth: true
            Layout.columnSpan: 2
            color: Material.accentColor
        }

        Label {
            id: amountLabel
            text: qsTr('Amount to send')
        }

        RowLayout {
            Layout.fillWidth: true
            Label {
                font.bold: true
                text: Config.formatSats(satoshis, false)
            }

            Label {
                text: Config.baseUnit
                color: Material.accentColor
            }

            Label {
                id: fiatValue
                Layout.fillWidth: true
                text: Daemon.fx.enabled
                        ? '(' + Daemon.fx.fiatValue(satoshis, false) + ' ' + Daemon.fx.fiatCurrency + ')'
                        : ''
                font.pixelSize: constants.fontSizeMedium
            }
        }

        Label {
            text: qsTr('Mining fee')
        }

        RowLayout {
            Label {
                id: fee
                text: Config.formatSats(finalizer.fee)
            }

            Label {
                text: Config.baseUnit
                color: Material.accentColor
            }
        }

        Label {
            text: qsTr('Fee rate')
        }

        RowLayout {
            Label {
                id: feeRate
                text: finalizer.feeRate
            }

            Label {
                text: 'sat/vB'
                color: Material.accentColor
            }
        }

        Label {
            text: qsTr('Target')
        }

        Label {
            id: targetdesc
            text: finalizer.target
        }

        Slider {
            id: feeslider
            snapMode: Slider.SnapOnRelease
            stepSize: 1
            from: 0
            to: finalizer.sliderSteps
            onValueChanged: {
                if (activeFocus)
                    finalizer.sliderPos = value
            }
            Component.onCompleted: {
                value = finalizer.sliderPos
            }
            Connections {
                target: finalizer
                function onSliderPosChanged() {
                    feeslider.value = finalizer.sliderPos
                }
            }
        }

        ComboBox {
            id: target
            textRole: 'text'
            valueRole: 'value'
            model: [
                { text: qsTr('ETA'), value: 1 },
                { text: qsTr('Mempool'), value: 2 },
                { text: qsTr('Static'), value: 0 }
            ]
            onCurrentValueChanged: {
                if (activeFocus)
                    finalizer.method = currentValue
            }
            Component.onCompleted: {
                currentIndex = indexOfValue(finalizer.method)
            }
        }

        InfoTextArea {
            Layout.columnSpan: 2
            visible: finalizer.warning != ''
            text: finalizer.warning
            iconStyle: InfoTextArea.IconStyle.Warn
        }

        CheckBox {
            id: final_cb
            text: qsTr('Replace-by-Fee')
            Layout.columnSpan: 2
            checked: finalizer.rbf
        }

        Rectangle {
            height: 1
            Layout.fillWidth: true
            Layout.columnSpan: 2
            color: Material.accentColor
        }

        Label {
            text: qsTr('Outputs')
            Layout.columnSpan: 2
        }

        Repeater {
            model: finalizer.outputs
            delegate: RowLayout {
                Layout.columnSpan: 2
                Label {
                    text: modelData.address
                }
                Label {
                    text: modelData.value_sats
                }
            }
        }

        Rectangle {
            height: 1
            Layout.fillWidth: true
            Layout.columnSpan: 2
            color: Material.accentColor
        }

        Item { Layout.fillHeight: true; Layout.preferredWidth: 1 }

        RowLayout {
            Layout.columnSpan: 2
            Layout.alignment: Qt.AlignHCenter

            Button {
                text: qsTr('Cancel')
                onClicked: dialog.close()
            }

            Button {
                id: sendButton
                text: qsTr('Pay')
                enabled: finalizer.valid
                onClicked: {
                    finalizer.send_onchain()
                    dialog.close()
                }
            }
        }
    }

}
