# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'click_colorui.ui'
#
# Created by: PyQt5 UI code generator 5.13.1
#
# WARNING! All changes made in this file will be lost!


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_Click_ColorUI(object):
    def setupUi(self, Click_ColorUI):
        Click_ColorUI.setObjectName("Click_ColorUI")
        Click_ColorUI.resize(260, 200)
        Click_ColorUI.setMinimumSize(QtCore.QSize(260, 200))
        Click_ColorUI.setMaximumSize(QtCore.QSize(260, 200))
        self.colors_ListWidget = QtWidgets.QListWidget(Click_ColorUI)
        self.colors_ListWidget.setGeometry(QtCore.QRect(10, 40, 241, 110))
        self.colors_ListWidget.setObjectName("colors_ListWidget")
        self.label = QtWidgets.QLabel(Click_ColorUI)
        self.label.setGeometry(QtCore.QRect(16, 12, 230, 21))
        self.label.setObjectName("label")
        self.click_color_PushButton = QtWidgets.QPushButton(Click_ColorUI)
        self.click_color_PushButton.setGeometry(QtCore.QRect(10, 160, 241, 31))
        self.click_color_PushButton.setObjectName("click_color_PushButton")

        self.retranslateUi(Click_ColorUI)
        QtCore.QMetaObject.connectSlotsByName(Click_ColorUI)

    def retranslateUi(self, Click_ColorUI):
        _translate = QtCore.QCoreApplication.translate
        Click_ColorUI.setWindowTitle(_translate("Click_ColorUI", "Выбор цвета"))
        self.colors_ListWidget.setToolTip(_translate("Click_ColorUI", "Список всех доступных цветов"))
        self.label.setText(_translate("Click_ColorUI", "Доступные цвета:"))
        self.click_color_PushButton.setToolTip(_translate("Click_ColorUI", "Приложение кликнет по выбранному цвету в игровой палитре"))
        self.click_color_PushButton.setText(_translate("Click_ColorUI", "Клик по цвету"))
